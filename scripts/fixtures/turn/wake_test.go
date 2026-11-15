package turn

import (
	"bytes"
	"net"
	"testing"
	"time"
)

// Short server lifetimes stand in for time spent suspended on the phone.
// The client timers deliberately do not fire during this interval. STUN must
// still answer, while the actual relayed payload fails until TURN is renewed.
func TestIOSWakeRestoresExpiredTURNDataPath(t *testing.T) {
	listener, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(ServerConfig{
		Realm: "wake-fixture",
		AuthHandler: func(a *RequestAttributes) (string, []byte, bool) {
			return a.Username, GenerateAuthKey(a.Username, a.Realm, "fixture"), true
		},
		PacketConnConfigs: []PacketConnConfig{{PacketConn: listener,
			RelayAddressGenerator: &RelayAddressGeneratorStatic{RelayAddress: net.IPv4(127, 0, 0, 1), Address: "127.0.0.1"}}},
		AllocationLifetime: time.Minute,
		PermissionTimeout:  100 * time.Millisecond,
		ChannelBindTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		listener.Close()
		t.Fatal(err)
	}
	defer server.Close()
	socket, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer socket.Close()
	tc, err := NewClient(&ClientConfig{Conn: socket, STUNServerAddr: listener.LocalAddr().String(),
		TURNServerAddr: listener.LocalAddr().String(), Username: "fixture", Password: "fixture",
		PermissionRefreshInterval: time.Hour, bindingRefreshInterval: time.Hour, bindingCheckInterval: time.Hour})
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
	defer relay.Close()
	peer, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	payload := []byte("real relayed packet")
	check := func(src, dst net.PacketConn, address net.Addr) error {
		dst.SetReadDeadline(time.Now().Add(250 * time.Millisecond))
		if _, e := src.WriteTo(payload, address); e != nil {
			return e
		}
		buf := make([]byte, 100)
		n, _, e := dst.ReadFrom(buf)
		if e == nil && !bytes.Equal(buf[:n], payload) {
			t.Fatalf("wrong payload: %q", buf[:n])
		}
		return e
	}
	if err = check(relay, peer, peer.LocalAddr()); err != nil {
		t.Fatalf("initial outbound: %v", err)
	}
	// Let the initial asynchronous ChannelBind settle, then expire both server
	// permission and channel. No allocation or UDP socket has changed.
	time.Sleep(350 * time.Millisecond)
	if _, err = tc.SendBindingRequest(); err != nil {
		t.Fatalf("STUN should remain healthy: %v", err)
	}
	if err = check(relay, peer, peer.LocalAddr()); err == nil {
		t.Fatal("fixture did not expire the data channel")
	}
	if resume, ok := relay.(interface{ Refresh() error }); ok {
		if err = resume.Refresh(); err != nil {
			t.Fatalf("renew existing TURN allocation: %v", err)
		}
	}
	if err = check(relay, peer, peer.LocalAddr()); err != nil {
		t.Fatalf("STUN answers and worker stays registered, but after wake outbound data is blackholed: %v", err)
	}
	if err = check(peer, relay, relay.LocalAddr()); err != nil {
		t.Fatalf("after wake inbound data is blackholed: %v", err)
	}
}
