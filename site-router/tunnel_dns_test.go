package main

import (
	"encoding/binary"
	"net/netip"
	"testing"
)

func TestTunnelDNSPreservesConfiguredResolverAndReplyAddress(t *testing.T) {
	proxy := newTunnelDNS()
	proxy.update([]string{"9.9.9.9"})
	packet := ruFixture("outside.test", false, [4]byte{})
	copy(packet[16:20], []byte{10, 66, 66, 53})
	binary.BigEndian.PutUint16(packet[10:12], packetChecksum(packet[:20], 0))
	proxy.outbound(packet)
	if address, _ := packetDestination(packet); address != netip.MustParseAddr("9.9.9.9") {
		t.Fatal("configured DNS lost")
	}
	if packetChecksum(packet[:20], 0) != 0 {
		t.Fatal("IP checksum invalid")
	}
	reply := russianReply(packet, 20, packet[28:])
	proxy.inbound(reply)
	if netip.AddrFrom4([4]byte(reply[12:16])) != tunnelDNSAddress {
		t.Fatal("reply source differs from system resolver")
	}
	if packetChecksum(reply[:20], 0) != 0 {
		t.Fatal("reply checksum invalid")
	}
	proxy.update([]string{"10.66.66.53", "invalid", "1.0.0.1"})
	if proxy.upstream != netip.MustParseAddr("1.0.0.1") {
		t.Fatal("proxy selected itself")
	}
}

func TestTunnelDNSRewritesTCPAndUDPChecksumsAndFragments(t *testing.T) {
	for _, protocol := range []byte{6, 17} {
		packet := make([]byte, 60)
		packet[0], packet[8], packet[9] = 0x45, 64, protocol
		binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))
		copy(packet[12:16], []byte{10, 66, 66, 2})
		copy(packet[16:20], []byte{10, 66, 66, 53})
		binary.BigEndian.PutUint16(packet[20:22], 53001)
		binary.BigEndian.PutUint16(packet[22:24], 53)
		checksumOffset := 26
		if protocol == 6 {
			checksumOffset = 36
			packet[32] = 0x50
		} else {
			binary.BigEndian.PutUint16(packet[24:26], 40)
		}
		pseudo := func() uint32 {
			sum := uint32(protocol) + 40
			for offset := 12; offset < 20; offset += 2 {
				sum += uint32(binary.BigEndian.Uint16(packet[offset : offset+2]))
			}
			return sum
		}
		binary.BigEndian.PutUint16(packet[checksumOffset:checksumOffset+2], packetChecksum(packet[20:], pseudo()))
		binary.BigEndian.PutUint16(packet[10:12], packetChecksum(packet[:20], 0))
		proxy := newTunnelDNS()
		proxy.outbound(packet)
		if packetChecksum(packet[20:], pseudo()) != 0 || packetChecksum(packet[:20], 0) != 0 {
			t.Fatalf("invalid protocol %d checksum", protocol)
		}
	}
	proxy := newTunnelDNS()
	first := ruFixture("outside.test", false, [4]byte{})
	copy(first[16:20], []byte{10, 66, 66, 53})
	binary.BigEndian.PutUint16(first[6:8], 0x2000)
	later := append([]byte(nil), first[:28]...)
	binary.BigEndian.PutUint16(later[6:8], 1)
	proxy.outbound(first)
	proxy.outbound(later)
	if address, _ := packetDestination(later); address != proxy.upstream {
		t.Fatal("fragment missed DNS translation")
	}
}
