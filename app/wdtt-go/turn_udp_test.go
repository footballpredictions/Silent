package main

import (
	"bytes"
	"context"
	"net"
	"testing"
	"time"

	"github.com/pion/turn/v5"
)

func TestUDPSelectionRetainsTestedEndpointOrder(t *testing.T) {
	urls := []string{"turn:first.example:3478?transport=udp", "turn:first.example:443?transport=tcp", "turns:secure.example:5349?transport=tcp", "second.example:4567"}
	for i := 0; i < 9; i++ {
		got, err := selectUDPEndpoint(urls, i, "", "")
		want := []udpEndpoint{{"first.example", "3478"}, {"second.example", "4567"}}[i%2]
		if err != nil || got != want {
			t.Fatalf("session %d: %+v %v, want %+v", i, got, err, want)
		}
	}
	response := map[string]interface{}{"turn_server": map[string]interface{}{"urls": []interface{}{urls[0], urls[1], urls[2], urls[3]}}}
	parsed := parseVKCallsTURNAddresses(response)
	if len(parsed) != 2 || parsed[0] != urls[0] || parsed[1] != urls[3] {
		t.Fatalf("UDP credentials changed: %v", parsed)
	}
	got, err := selectUDPEndpoint(urls, 1, "127.0.0.1", "1234")
	if err != nil || got != (udpEndpoint{"127.0.0.1", "1234"}) {
		t.Fatalf("override: %+v %v", got, err)
	}
}

func TestUDPRejectsStreamEndpointsAndInvalidAddresses(t *testing.T) {
	for _, raw := range []string{"turn:relay.example?transport=tcp", "turns:relay.example", "https://relay.example", "turn:user:password@relay.example:3478", "turn:relay.example:0", "turn:relay.example:3478\ninvalid"} {
		if _, err := parseUDPEndpoint(raw); err == nil {
			t.Fatalf("non-UDP/invalid endpoint accepted: %q", raw)
		}
	}
	for _, raw := range []string{"turn:relay.example", "relay.example:3478", "turn:[::1]:3478?transport=udp"} {
		if _, err := parseUDPEndpoint(raw); err != nil {
			t.Fatalf("valid UDP endpoint rejected: %q: %v", raw, err)
		}
	}
	if _, err := selectUDPEndpoint([]string{"turns:relay.example"}, 0, "", ""); err == nil {
		t.Fatal("must not dial stream-only provider address over UDP")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, _, err := dialUDPTURN(ctx, []string{"127.0.0.1:1"}, 0, &TurnParams{}); err == nil {
		t.Fatal("canceled dial succeeded")
	}
}

// Real allocation and bidirectional datagrams through the same Android adapter.
func TestUDPActualRelayWithMobileNet(t *testing.T) {
	conn, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	addr := conn.LocalAddr().String()
	server, err := turn.NewServer(turn.ServerConfig{Realm: "transport.test", AuthHandler: func(a *turn.RequestAttributes) (string, []byte, bool) {
		return a.Username, turn.GenerateAuthKey(a.Username, a.Realm, "fixture-pass"), true
	}, PacketConnConfigs: []turn.PacketConnConfig{{PacketConn: conn, RelayAddressGenerator: &turn.RelayAddressGeneratorStatic{RelayAddress: net.ParseIP("127.0.0.1"), Address: "127.0.0.1"}}}})
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	transport, _, err := dialUDPTURN(ctx, []string{"turn:" + addr + "?transport=udp"}, 0, &TurnParams{})
	if err != nil {
		t.Fatal(err)
	}
	defer transport.Close()
	client, err := turn.NewClient(&turn.ClientConfig{Conn: transport, STUNServerAddr: addr, TURNServerAddr: addr, Username: "fixture", Password: "fixture-pass", RTO: 40 * time.Millisecond, Net: mobileNet{}})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if err = client.Listen(); err != nil {
		t.Fatal(err)
	}
	relay, err := client.Allocate()
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	peer, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	for _, size := range []int{64, 1400, 512, 127} {
		payload := bytes.Repeat([]byte{byte(size % 251)}, size)
		_ = peer.SetDeadline(time.Now().Add(2 * time.Second))
		_ = relay.SetDeadline(time.Now().Add(2 * time.Second))
		if _, err = relay.WriteTo(payload, peer.LocalAddr()); err != nil {
			t.Fatal(err)
		}
		buf := make([]byte, 2048)
		n, source, err := peer.ReadFrom(buf)
		if err != nil || !bytes.Equal(buf[:n], payload) {
			t.Fatalf("upstream datagram: %v", err)
		}
		if _, err = peer.WriteTo(buf[:n], source); err != nil {
			t.Fatal(err)
		}
		n, _, err = relay.ReadFrom(buf)
		if err != nil || !bytes.Equal(buf[:n], payload) {
			t.Fatalf("downstream datagram: %v", err)
		}
	}
}
