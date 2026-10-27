package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"sync"
	"testing"
	"time"
)

// An actual dispatcher input, without credentials, TURN, VPN or external traffic.
type dispatchFixtureConn struct {
	input       chan []byte
	closed      chan struct{}
	once        sync.Once
	readEntered chan struct{}
	readOnce    sync.Once
}

func (c *dispatchFixtureConn) ReadFrom(b []byte) (int, net.Addr, error) {
	if c.readEntered != nil {
		c.readOnce.Do(func() { close(c.readEntered) })
	}
	select {
	case p := <-c.input:
		return copy(b, p), &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 1}, nil
	case <-c.closed:
		return 0, nil, io.EOF
	}
}

func TestDispatcherShutdownUnblocksIdleReader(t *testing.T) {
	c := &dispatchFixtureConn{input: make(chan []byte), closed: make(chan struct{}), readEntered: make(chan struct{})}
	d := NewDispatcher(context.Background(), c, NewStats())
	<-c.readEntered
	done := make(chan struct{})
	go func() { d.Shutdown(); close(done) }()
	select {
	case <-done:
	case <-time.After(300 * time.Millisecond):
		c.Close()
		<-done
		t.Fatal("Shutdown waited on an idle packet read; GUI must force-kill the old transport")
	}
}
func (c *dispatchFixtureConn) WriteTo(b []byte, _ net.Addr) (int, error) { return len(b), nil }
func (c *dispatchFixtureConn) Close() error                              { c.once.Do(func() { close(c.closed) }); return nil }
func (c *dispatchFixtureConn) LocalAddr() net.Addr                       { return &net.UDPAddr{} }
func (c *dispatchFixtureConn) SetDeadline(time.Time) error               { return nil }
func (c *dispatchFixtureConn) SetReadDeadline(time.Time) error           { return nil }
func (c *dispatchFixtureConn) SetWriteDeadline(time.Time) error          { return nil }

func TestDispatcherUsesEveryReadyRelay(t *testing.T) {
	for _, packetSize := range []int{64, 1200} {
		for _, n := range []int{9, 11, 22, 33, 36, 44, 55, 63, 66, 77, 88, 99, 108} {
			t.Run(fmt.Sprintf("workers=%d/bytes=%d", n, packetSize), func(t *testing.T) {
				c := &dispatchFixtureConn{input: make(chan []byte, n*chunkSize), closed: make(chan struct{})}
				d := NewDispatcher(context.Background(), c, NewStats())
				defer func() { c.Close(); d.Shutdown() }()
				slots := make([]*WorkerSlot, n)
				for i := range slots {
					slots[i] = &WorkerSlot{ID: i, SendCh: make(chan []byte, n*chunkSize)}
					d.Register(slots[i])
				}
				for i := 0; i < n*chunkSize; i++ {
					packet := make([]byte, packetSize)
					binary.BigEndian.PutUint32(packet, uint32(i))
					c.input <- packet
				}
				deadline := time.Now().Add(2 * time.Second)
				for {
					total := 0
					for _, s := range slots {
						total += len(s.SendCh)
					}
					if total == n*chunkSize {
						break
					}
					if time.Now().After(deadline) {
						t.Fatal("dispatcher did not drain fixture")
					}
					time.Sleep(time.Millisecond)
				}
				used := 0
				for _, s := range slots {
					if len(s.SendCh) > 0 {
						used++
					}
				}
				if used != n {
					t.Errorf("ready=%d but upload/ACK chunks only use %d relays", n, used)
				}
				if used == n {
					for _, slot := range slots {
						if len(slot.SendCh) != chunkSize {
							t.Fatalf("worker %d has unbalanced chunk: %d", slot.ID, len(slot.SendCh))
						}
						first := uint32(0)
						for i := 0; i < chunkSize; i++ {
							packet := <-slot.SendCh
							seq := binary.BigEndian.Uint32(packet)
							if i == 0 {
								first = seq
							}
							if seq != first+uint32(i) {
								t.Fatalf("chunk order changed on worker %d", slot.ID)
							}
							putPktBuf(packet)
						}
					}
				}
			})
		}
	}
}
