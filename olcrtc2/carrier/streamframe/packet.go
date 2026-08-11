package streamframe

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"sync"
)

// PacketConn adapts a reliable stream (e.g. olcrtc Dial net.Conn) to PacketConn.
type PacketConn struct {
	c      net.Conn
	readMu sync.Mutex
	writeMu sync.Mutex
	closed chan struct{}
	once   sync.Once
}

func Wrap(c net.Conn) *PacketConn {
	return &PacketConn{c: c, closed: make(chan struct{})}
}

func (p *PacketConn) ReadPacket(ctx context.Context) ([]byte, error) {
	type result struct {
		b   []byte
		err error
	}
	ch := make(chan result, 1)
	go func() {
		p.readMu.Lock()
		defer p.readMu.Unlock()
		var hdr [4]byte
		if _, err := io.ReadFull(p.c, hdr[:]); err != nil {
			ch <- result{err: err}
			return
		}
		n := binary.BigEndian.Uint32(hdr[:])
		if n == 0 || n > 512*1024 {
			ch <- result{err: errors.New("bad frame length")}
			return
		}
		buf := make([]byte, n)
		if _, err := io.ReadFull(p.c, buf); err != nil {
			ch <- result{err: err}
			return
		}
		ch <- result{b: buf}
	}()
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-p.closed:
		return nil, errors.New("closed")
	case r := <-ch:
		return r.b, r.err
	}
}

func (p *PacketConn) WritePacket(ctx context.Context, b []byte) error {
	if len(b) > 512*1024 {
		return errors.New("packet too large")
	}
	done := make(chan error, 1)
	go func() {
		p.writeMu.Lock()
		defer p.writeMu.Unlock()
		var hdr [4]byte
		binary.BigEndian.PutUint32(hdr[:], uint32(len(b)))
		if _, err := p.c.Write(hdr[:]); err != nil {
			done <- err
			return
		}
		_, err := p.c.Write(b)
		done <- err
	}()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-p.closed:
		return errors.New("closed")
	case err := <-done:
		return err
	}
}

func (p *PacketConn) Close() error {
	p.once.Do(func() { close(p.closed) })
	return p.c.Close()
}
