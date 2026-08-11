package olcrtc2

import (
	"context"
	"errors"
	"sync"
)

// MockCarrier is an in-process loopback for Phase 0/1 tests (no SFU).
type MockCarrier struct {
	name Provider
	mu   sync.Mutex
	dead bool
}

func NewMockCarrier(p Provider) *MockCarrier {
	return &MockCarrier{name: p}
}

func (m *MockCarrier) Provider() Provider { return m.name }

// Dial returns one end of a linked pipe (peer discarded). Prefer DialPair for cnc+srv.
func (m *MockCarrier) Dial(ctx context.Context, session Session) (PacketConn, error) {
	a, b, err := m.DialPair(ctx, session)
	if err != nil {
		return nil, err
	}
	_ = b.Close()
	return a, nil
}

// DialPair returns linked PacketConns: cnc side and srv side.
func (m *MockCarrier) DialPair(ctx context.Context, session Session) (cnc, srv PacketConn, err error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dead {
		return nil, nil, errors.New("mock carrier closed")
	}
	if session.RoomID == "" {
		return nil, nil, errors.New("empty room id")
	}
	a, b := newPipePair()
	return a, b, nil
}

func (m *MockCarrier) Close() error {
	m.mu.Lock()
	m.dead = true
	m.mu.Unlock()
	return nil
}

type memPipe struct {
	in     chan []byte
	out    chan []byte
	closed chan struct{}
	once   sync.Once
}

func newPipePair() (*memPipe, *memPipe) {
	ab := make(chan []byte, 64)
	ba := make(chan []byte, 64)
	ca := make(chan struct{})
	cb := make(chan struct{})
	return &memPipe{in: ba, out: ab, closed: ca}, &memPipe{in: ab, out: ba, closed: cb}
}

func (p *memPipe) ReadPacket(ctx context.Context) ([]byte, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-p.closed:
		return nil, errors.New("pipe closed")
	case b, ok := <-p.in:
		if !ok {
			return nil, errors.New("pipe closed")
		}
		return b, nil
	}
}

func (p *memPipe) WritePacket(ctx context.Context, b []byte) error {
	cp := append([]byte(nil), b...)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-p.closed:
		return errors.New("pipe closed")
	case p.out <- cp:
		return nil
	}
}

func (p *memPipe) Close() error {
	p.once.Do(func() {
		close(p.closed)
	})
	return nil
}
