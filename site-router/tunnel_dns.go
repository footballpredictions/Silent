package main

import (
	"encoding/binary"
	"net/netip"
	"sync"
	"time"
)

var tunnelDNSAddress = netip.MustParseAddr("10.66.66.53")

type tunnelDNS struct {
	mu        sync.Mutex
	upstream  netip.Addr
	flows     map[flow]time.Time
	fragments map[fragmentKey]dnsFragment
}

type dnsFragment struct {
	address netip.Addr
	expires time.Time
}

func newTunnelDNS() *tunnelDNS {
	return &tunnelDNS{upstream: netip.MustParseAddr("1.1.1.1"), flows: make(map[flow]time.Time), fragments: make(map[fragmentKey]dnsFragment)}
}

func (proxy *tunnelDNS) update(servers []string) {
	if proxy == nil {
		return
	}
	for _, server := range servers {
		address, err := netip.ParseAddr(server)
		if err == nil && address.Is4() && address != tunnelDNSAddress {
			proxy.mu.Lock()
			proxy.upstream = address
			proxy.mu.Unlock()
			return
		}
	}
}

func (proxy *tunnelDNS) outbound(packet []byte) {
	if proxy == nil {
		return
	}
	if proxy.fragment(packet, 16) {
		return
	}
	connection, address, ok := packetFlow(packet)
	if !ok || address != tunnelDNSAddress {
		return
	}
	remote, err := netip.ParseAddrPort(connection.Remote)
	if err != nil || remote.Port() != 53 {
		return
	}
	proxy.mu.Lock()
	defer proxy.mu.Unlock()
	upstream := proxy.upstream
	connection.Remote = netip.AddrPortFrom(upstream, 53).String()
	now := time.Now()
	if _, exists := proxy.flows[connection]; !exists && len(proxy.flows) >= 4096 {
		for key, until := range proxy.flows {
			if now.After(until) {
				delete(proxy.flows, key)
			}
		}
		if len(proxy.flows) >= 4096 {
			return
		}
	}
	proxy.flows[connection] = now.Add(10 * time.Minute)
	rewriteDNSAddress(packet, 16, upstream)
	proxy.rememberFragment(packet, 16, tunnelDNSAddress, upstream)
}

func (proxy *tunnelDNS) inbound(packet []byte) {
	if proxy == nil {
		return
	}
	if proxy.fragment(packet, 12) {
		return
	}
	connection, _, ok := packetFlow(packet)
	if !ok {
		return
	}
	connection.Local, connection.Remote = connection.Remote, connection.Local
	proxy.mu.Lock()
	until, found := proxy.flows[connection]
	proxy.mu.Unlock()
	if found && time.Now().Before(until) {
		original := netip.AddrFrom4([4]byte(packet[12:16]))
		rewriteDNSAddress(packet, 12, tunnelDNSAddress)
		proxy.mu.Lock()
		proxy.rememberFragment(packet, 12, original, tunnelDNSAddress)
		proxy.mu.Unlock()
	}
}

func (proxy *tunnelDNS) rememberFragment(packet []byte, offset int, original, translated netip.Addr) {
	if binary.BigEndian.Uint16(packet[6:8])&0x2000 == 0 {
		return
	}
	key := fragmentKey{[4]byte(packet[12:16]), [4]byte(packet[16:20]), binary.BigEndian.Uint16(packet[4:6]), packet[9]}
	if offset == 12 {
		key.Source = original.As4()
	} else {
		key.Destination = original.As4()
	}
	if len(proxy.fragments) >= 512 {
		clear(proxy.fragments)
	}
	proxy.fragments[key] = dnsFragment{address: translated, expires: time.Now().Add(30 * time.Second)}
}

func (proxy *tunnelDNS) fragment(packet []byte, offset int) bool {
	if len(packet) < 20 || packet[0]>>4 != 4 || binary.BigEndian.Uint16(packet[6:8])&0x1fff == 0 {
		return false
	}
	key := fragmentKey{[4]byte(packet[12:16]), [4]byte(packet[16:20]), binary.BigEndian.Uint16(packet[4:6]), packet[9]}
	proxy.mu.Lock()
	fragment, found := proxy.fragments[key]
	proxy.mu.Unlock()
	if found && time.Now().Before(fragment.expires) {
		rewriteDNSAddress(packet, offset, fragment.address)
	}
	return true
}

func rewriteDNSAddress(packet []byte, offset int, address netip.Addr) {
	headerLength := int(packet[0]&15) * 4
	checksumOffset := headerLength + 6
	if packet[9] == 6 {
		checksumOffset = headerLength + 16
	}
	if headerLength < 20 || len(packet) < headerLength {
		return
	}
	previous := [4]byte(packet[offset : offset+4])
	next := address.As4()
	adjust := func(checksum uint16) uint16 {
		sum := uint32(^checksum)
		for word := 0; word < 4; word += 2 {
			sum += uint32(^binary.BigEndian.Uint16(previous[word:word+2])) + uint32(binary.BigEndian.Uint16(next[word:word+2]))
		}
		for sum>>16 != 0 {
			sum = (sum & 0xffff) + (sum >> 16)
		}
		return ^uint16(sum)
	}
	if binary.BigEndian.Uint16(packet[6:8])&0x1fff == 0 && len(packet) >= checksumOffset+2 {
		checksum := binary.BigEndian.Uint16(packet[checksumOffset : checksumOffset+2])
		if packet[9] == 6 || checksum != 0 {
			checksum = adjust(checksum)
			if checksum == 0 && packet[9] == 17 {
				checksum = 0xffff
			}
			binary.BigEndian.PutUint16(packet[checksumOffset:checksumOffset+2], checksum)
		}
	}
	binary.BigEndian.PutUint16(packet[10:12], adjust(binary.BigEndian.Uint16(packet[10:12])))
	copy(packet[offset:offset+4], next[:])
}
