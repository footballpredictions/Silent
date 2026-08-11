package edge

import (
	"context"
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	"github.com/xtaci/smux"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
	"github.com/footballpredictions/Silent/olcrtc2/secure"
)

// Link is one side of a smux session over AEAD PacketConn.
type Link struct {
	session *smux.Session
	secure  *secure.Conn
}

func OpenLink(pc olcrtc2.PacketConn, key []byte, isClient bool) (*Link, error) {
	sc, err := secure.Wrap(pc, key)
	if err != nil {
		return nil, err
	}
	cfg := smux.DefaultConfig()
	cfg.Version = 2
	cfg.KeepAliveTimeout = 30 * time.Second
	var sess *smux.Session
	if isClient {
		sess, err = smux.Client(sc, cfg)
	} else {
		sess, err = smux.Server(sc, cfg)
	}
	if err != nil {
		_ = sc.Close()
		return nil, err
	}
	return &Link{session: sess, secure: sc}, nil
}

func (l *Link) Close() error {
	if l.session != nil {
		_ = l.session.Close()
	}
	if l.secure != nil {
		return l.secure.Close()
	}
	return nil
}

func (l *Link) OpenStream() (*smux.Stream, error) { return l.session.OpenStream() }
func (l *Link) AcceptStream() (*smux.Stream, error) {
	return l.session.AcceptStream()
}

// LoopbackPair wires CNC SOCKS ↔ SRV egress over MockCarrier (no SFU).
type LoopbackPair struct {
	SocksAddr string
	socksLn   net.Listener
	cncLink   *Link
	srvLink   *Link
	cancel    context.CancelFunc
	wg        sync.WaitGroup
}

// StartLoopback brings up SOCKS5 on socksHost (e.g. 127.0.0.1:0) and srv egress.
func StartLoopback(ctx context.Context, keyHex, socksHost string) (*LoopbackPair, error) {
	key, err := secure.ParseKeyHex(keyHex)
	if err != nil {
		return nil, err
	}
	mock := olcrtc2.NewMockCarrier(olcrtc2.ProviderTelemost)
	cncPC, srvPC, err := mock.DialPair(ctx, olcrtc2.Session{
		Provider:  olcrtc2.ProviderTelemost,
		RoomID:    "loopback",
		CryptoKey: keyHex,
	})
	if err != nil {
		return nil, err
	}

	// SRV must accept smux before CNC opens streams — start server link first.
	srvLink, err := OpenLink(srvPC, key, false)
	if err != nil {
		_ = cncPC.Close()
		_ = srvPC.Close()
		return nil, fmt.Errorf("srv link: %w", err)
	}
	cncLink, err := OpenLink(cncPC, key, true)
	if err != nil {
		_ = srvLink.Close()
		_ = cncPC.Close()
		return nil, fmt.Errorf("cnc link: %w", err)
	}

	ln, err := net.Listen("tcp", socksHost)
	if err != nil {
		_ = cncLink.Close()
		_ = srvLink.Close()
		return nil, err
	}

	runCtx, cancel := context.WithCancel(ctx)
	p := &LoopbackPair{
		SocksAddr: ln.Addr().String(),
		socksLn:   ln,
		cncLink:   cncLink,
		srvLink:   srvLink,
		cancel:    cancel,
	}

	p.wg.Add(2)
	go func() {
		defer p.wg.Done()
		_ = runSRV(runCtx, srvLink)
	}()
	go func() {
		defer p.wg.Done()
		_ = serveSOCKS(runCtx, ln, cncLink)
	}()

	return p, nil
}

func (p *LoopbackPair) Close() error {
	if p.cancel != nil {
		p.cancel()
	}
	if p.socksLn != nil {
		_ = p.socksLn.Close()
	}
	seen := map[*Link]struct{}{}
	for _, l := range []*Link{p.cncLink, p.srvLink} {
		if l == nil {
			continue
		}
		if _, ok := seen[l]; ok {
			continue
		}
		seen[l] = struct{}{}
		_ = l.Close()
	}
	p.wg.Wait()
	return nil
}

func runSRV(ctx context.Context, link *Link) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		stream, err := link.AcceptStream()
		if err != nil {
			return err
		}
		go handleSRVStream(ctx, stream)
	}
}

func handleSRVStream(ctx context.Context, stream *smux.Stream) {
	defer stream.Close()
	_ = stream.SetDeadline(time.Now().Add(60 * time.Second))
	target, err := readTarget(stream)
	if err != nil {
		return
	}
	var d net.Dialer
	conn, err := d.DialContext(ctx, "tcp", target)
	if err != nil {
		return
	}
	defer conn.Close()
	_ = stream.SetDeadline(time.Time{})
	bidirCopy(stream, conn)
}

func serveSOCKS(ctx context.Context, ln net.Listener, link *Link) error {
	for {
		conn, err := ln.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return ctx.Err()
			default:
				return err
			}
		}
		go func(c net.Conn) {
			defer c.Close()
			_ = handleSOCKS(ctx, c, link)
		}(conn)
	}
}

func bidirCopy(a, b net.Conn) {
	done := make(chan struct{}, 2)
	go func() { _, _ = io.Copy(a, b); done <- struct{}{} }()
	go func() { _, _ = io.Copy(b, a); done <- struct{}{} }()
	<-done
	_ = a.Close()
	_ = b.Close()
	<-done
}
