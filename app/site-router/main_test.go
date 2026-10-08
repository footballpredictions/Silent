//go:build linux || android

package main

import (
	"bytes"
	"io"
	"net/netip"
	"os"
	"testing"
)

func TestWireGuardDNSReplyUpdatesBrowserPolicyBeforeDelivery(t *testing.T) {
	p := newPolicy(true, []string{"172.67.134.103/32"}, []int{10001})
	p.domains = []string{"2ip.io"}
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	defer writer.Close()
	adapter := &routedTun{file: writer, policy: p}
	packet := answerPacket(t, "static.2ip.io", [4]byte{188, 114, 97, 3}, 60)
	buffer := append(make([]byte, 16), packet...)
	if n, err := adapter.Write([][]byte{buffer}, 16); n != 1 || err != nil {
		t.Fatalf("reply write: %d %v", n, err)
	}
	if p.direct(10001, netip.MustParseAddr("188.114.97.3")) {
		t.Fatal("browser would bypass the selected site's CDN after receiving its DNS answer")
	}
	delivered := make([]byte, len(packet))
	if _, err := io.ReadFull(reader, delivered); err != nil || !bytes.Equal(delivered, packet) {
		t.Fatal("DNS learning changed the response packet")
	}
	if p.direct(10002, netip.MustParseAddr("188.114.97.3")) {
		t.Fatal("DNS observation changed non-browser routing")
	}
}
