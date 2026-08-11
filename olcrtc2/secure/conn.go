package secure

import (
	"context"
	"crypto/cipher"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"sync"
	"time"

	"golang.org/x/crypto/chacha20poly1305"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
)

const (
	nonceSize = chacha20poly1305.NonceSizeX // 24
	maxPlain  = 48 * 1024
)

// ParseKeyHex accepts 64 hex chars → 32-byte XChaCha20-Poly1305 key.
func ParseKeyHex(s string) ([]byte, error) {
	b, err := hex.DecodeString(s)
	if err != nil {
		return nil, err
	}
	if len(b) != chacha20poly1305.KeySize {
		return nil, errors.New("crypto key must be 32 bytes (64 hex)")
	}
	return b, nil
}

// Conn turns an ordered PacketConn into a reliable net.Conn with AEAD packets.
type Conn struct {
	pc   olcrtc2.PacketConn
	aead cipher.AEAD

	readMu  sync.Mutex
	readBuf []byte

	writeMu sync.Mutex

	rDeadline time.Time
	wDeadline time.Time
	deadMu    sync.Mutex

	local  net.Addr
	remote net.Addr
}

func Wrap(pc olcrtc2.PacketConn, key []byte) (*Conn, error) {
	aead, err := chacha20poly1305.NewX(key)
	if err != nil {
		return nil, err
	}
	return &Conn{
		pc:     pc,
		aead:   aead,
		local:  stubAddr("olcrtc2-local"),
		remote: stubAddr("olcrtc2-remote"),
	}, nil
}

type stubAddr string

func (s stubAddr) Network() string { return "olcrtc2" }
func (s stubAddr) String() string  { return string(s) }

func (c *Conn) Read(p []byte) (int, error) {
	c.readMu.Lock()
	defer c.readMu.Unlock()
	for len(c.readBuf) == 0 {
		ctx, cancel := c.readCtx()
		pkt, err := c.pc.ReadPacket(ctx)
		cancel()
		if err != nil {
			return 0, err
		}
		plain, err := c.open(pkt)
		if err != nil {
			return 0, err
		}
		c.readBuf = plain
	}
	n := copy(p, c.readBuf)
	c.readBuf = c.readBuf[n:]
	return n, nil
}

func (c *Conn) Write(p []byte) (int, error) {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	sent := 0
	for sent < len(p) {
		chunk := p[sent:]
		if len(chunk) > maxPlain {
			chunk = chunk[:maxPlain]
		}
		sealed, err := c.seal(chunk)
		if err != nil {
			return sent, err
		}
		ctx, cancel := c.writeCtx()
		err = c.pc.WritePacket(ctx, sealed)
		cancel()
		if err != nil {
			return sent, err
		}
		sent += len(chunk)
	}
	return sent, nil
}

func (c *Conn) Close() error { return c.pc.Close() }

func (c *Conn) LocalAddr() net.Addr  { return c.local }
func (c *Conn) RemoteAddr() net.Addr { return c.remote }

func (c *Conn) SetDeadline(t time.Time) error {
	c.deadMu.Lock()
	c.rDeadline, c.wDeadline = t, t
	c.deadMu.Unlock()
	return nil
}
func (c *Conn) SetReadDeadline(t time.Time) error {
	c.deadMu.Lock()
	c.rDeadline = t
	c.deadMu.Unlock()
	return nil
}
func (c *Conn) SetWriteDeadline(t time.Time) error {
	c.deadMu.Lock()
	c.wDeadline = t
	c.deadMu.Unlock()
	return nil
}

func (c *Conn) readCtx() (context.Context, context.CancelFunc) {
	c.deadMu.Lock()
	d := c.rDeadline
	c.deadMu.Unlock()
	if d.IsZero() {
		return context.WithCancel(context.Background())
	}
	return context.WithDeadline(context.Background(), d)
}

func (c *Conn) writeCtx() (context.Context, context.CancelFunc) {
	c.deadMu.Lock()
	d := c.wDeadline
	c.deadMu.Unlock()
	if d.IsZero() {
		return context.WithCancel(context.Background())
	}
	return context.WithDeadline(context.Background(), d)
}

func (c *Conn) seal(plain []byte) ([]byte, error) {
	nonce := make([]byte, nonceSize)
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	ct := c.aead.Seal(nil, nonce, plain, nil)
	out := make([]byte, 2+nonceSize+len(ct))
	binary.BigEndian.PutUint16(out[:2], uint16(nonceSize+len(ct)))
	copy(out[2:2+nonceSize], nonce)
	copy(out[2+nonceSize:], ct)
	return out, nil
}

func (c *Conn) open(pkt []byte) ([]byte, error) {
	if len(pkt) < 2+nonceSize+c.aead.Overhead() {
		return nil, errors.New("short packet")
	}
	n := int(binary.BigEndian.Uint16(pkt[:2]))
	body := pkt[2:]
	if len(body) < n {
		return nil, io.ErrUnexpectedEOF
	}
	body = body[:n]
	if len(body) < nonceSize+c.aead.Overhead() {
		return nil, io.ErrUnexpectedEOF
	}
	nonce := body[:nonceSize]
	ct := body[nonceSize:]
	return c.aead.Open(nil, nonce, ct, nil)
}
