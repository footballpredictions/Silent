package main

import (
	"net"
	"sync"
)

// Own the allocation and its UDP socket together. Cancellation must first send
// Refresh(lifetime=0) on the still-open socket, then unblock transport reads.
// sync.Once on a relay alone is insufficient: attaching a just-allocated relay
// can race with cancellation while Allocate is returning.
type iosTURNTransport struct {
	mu     sync.Mutex
	socket net.PacketConn
	relay  net.PacketConn
	closed bool
}

func newIOSTURNTransport(socket net.PacketConn) *iosTURNTransport {
	return &iosTURNTransport{socket: socket}
}

func (t *iosTURNTransport) attach(relay net.PacketConn) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		_ = relay.Close()
		return false
	}
	t.relay = relay
	return true
}

func (t *iosTURNTransport) close() {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return
	}
	t.closed = true
	if t.relay != nil {
		_ = t.relay.Close()
	}
	_ = t.socket.Close()
}
