package edge

import (
	"context"
	"fmt"
	"net"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
	"github.com/footballpredictions/Silent/olcrtc2/secure"
)

// StartEdge brings up SOCKS (cnc) or egress-only (srv) over an already-dialed PacketConn.
func StartEdge(ctx context.Context, mode olcrtc2.EdgeMode, keyHex string, pc olcrtc2.PacketConn, socksHost string) (*LoopbackPair, error) {
	key, err := secure.ParseKeyHex(keyHex)
	if err != nil {
		return nil, err
	}
	isClient := mode == olcrtc2.ModeCNC
	link, err := OpenLink(pc, key, isClient)
	if err != nil {
		return nil, err
	}

	runCtx, cancel := context.WithCancel(ctx)
	p := &LoopbackPair{
		cancel: cancel,
	}

	if mode == olcrtc2.ModeSRV {
		p.srvLink = link
		p.wg.Add(1)
		go func() {
			defer p.wg.Done()
			_ = runSRV(runCtx, link)
		}()
		return p, nil
	}

	ln, err := net.Listen("tcp", socksHost)
	if err != nil {
		cancel()
		_ = link.Close()
		return nil, err
	}
	p.cncLink = link
	p.socksLn = ln
	p.SocksAddr = ln.Addr().String()
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		_ = serveSOCKS(runCtx, ln, link)
	}()
	return p, nil
}

// StartCarrierEdge dials the carrier then starts cnc/srv edge.
func StartCarrierEdge(ctx context.Context, mode olcrtc2.EdgeMode, keyHex, socksHost string, dial func(context.Context) (olcrtc2.PacketConn, error)) (*LoopbackPair, error) {
	pc, err := dial(ctx)
	if err != nil {
		return nil, err
	}
	p, err := StartEdge(ctx, mode, keyHex, pc, socksHost)
	if err != nil {
		_ = pc.Close()
		return nil, fmt.Errorf("edge: %w", err)
	}
	return p, nil
}
