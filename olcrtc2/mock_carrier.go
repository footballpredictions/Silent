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

func (m *MockCarrier) Dial(ctx context.Context, session Session) (PacketConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dead {
		return nil, errors.New("mock carrier closed")
	}
	if session.RoomID == "" {
		return nil, errors.New("empty room id")
	}
	a, b := newPipePair()
	_ = b // peer side would be srv; tests use one end
	return a, nil
}

func (m *MockCarrier) Close() error {
	m.mu.Lock()
	m.dead = true
	m.mu.Unlock()
	return nil
}

type memPipe struct {
	in   chan []byte
	out  chan []byte
	once sync.Once
}

func newPipePair() (*memPipe, *memPipe) {
	ab := make(chan []byte, 16)
	ba := make(chan []byte, 16)
	return &memPipe{in: ba, out: ab}, &memPipe{in: ab, out: ba}
}

func (p *memPipe) ReadPacket(ctx context.Context) ([]byte, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
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
	case p.out <- cp:
		return nil
	}
}

func (p *memPipe) Close() error {
	p.once.Do(func() {
		close(p.out)
	})
	return nil
}
