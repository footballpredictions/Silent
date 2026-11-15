package turn

import (
	"context"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/pion/stun/v3"
	"github.com/pion/turn/v5/internal/proto"
)

type iosRecordingSocket struct {
	net.PacketConn
	deallocated atomic.Bool
	closed      chan struct{}
	once        sync.Once
}

func (s *iosRecordingSocket) WriteTo(data []byte, addr net.Addr) (int, error) {
	message := &stun.Message{Raw: data}
	if message.Decode() == nil && message.Type.Method == stun.MethodRefresh {
		var lifetime proto.Lifetime
		if lifetime.GetFrom(message) == nil && lifetime.Duration == 0 {
			s.deallocated.Store(true)
		}
	}
	return s.PacketConn.WriteTo(data, addr)
}
func (s *iosRecordingSocket) Close() error {
	err := s.PacketConn.Close()
	s.once.Do(func() { close(s.closed) })
	return err
}

func TestIOSCancelReleasesTURNBeforeClosingUDPSocket(t *testing.T) {
	listener, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(ServerConfig{Realm: "cleanup-fixture",
		AuthHandler: func(a *RequestAttributes) (string, []byte, bool) {
			return a.Username, GenerateAuthKey(a.Username, a.Realm, "fixture"), true
		},
		PacketConnConfigs: []PacketConnConfig{{PacketConn: listener, RelayAddressGenerator: &RelayAddressGeneratorStatic{RelayAddress: net.IPv4(127, 0, 0, 1), Address: "127.0.0.1"}}}})
	if err != nil {
		listener.Close()
		t.Fatal(err)
	}
	defer server.Close()
	socket, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	record := &iosRecordingSocket{PacketConn: socket, closed: make(chan struct{})}
	defer record.Close()
	tc, err := NewClient(&ClientConfig{Conn: record, STUNServerAddr: listener.LocalAddr().String(), TURNServerAddr: listener.LocalAddr().String(), Username: "fixture", Password: "fixture"})
	if err != nil {
		t.Fatal(err)
	}
	defer tc.Close()
	if err = tc.Listen(); err != nil {
		t.Fatal(err)
	}
	relay, err := tc.Allocate()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	release, done, ready := make(chan struct{}), make(chan struct{}), make(chan struct{})
	go func() { defer close(done); iosCancelSessionFixture(ctx, record, relay, ready, release) }()
	<-ready
	cancel()
	select {
	case <-record.closed:
	case <-time.After(time.Second):
		t.Fatal("cancel did not unblock UDP transport")
	}
	deallocated := record.deallocated.Load()
	close(release)
	<-done
	if !deallocated {
		t.Fatal("UDP socket closed before TURN Refresh(lifetime=0); allocation leaks until expiry and consumes relay quota")
	}
}
