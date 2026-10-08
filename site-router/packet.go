package main

import (
	"encoding/binary"
	"net/netip"
	"strconv"
)

type flow struct {
	Protocol int    `json:"protocol"`
	Local    string `json:"local"`
	Remote   string `json:"remote"`
}

func portString(port uint16) string { return strconv.Itoa(int(port)) }
func packetDestination(p []byte) (netip.Addr, bool) {
	if len(p) < 20 || p[0]>>4 != 4 {
		return netip.Addr{}, false
	}
	return netip.AddrFrom4([4]byte(p[16:20])), true
}
func packetFlow(p []byte) (flow, netip.Addr, bool) {
	if len(p) < 20 || p[0]>>4 != 4 {
		return flow{}, netip.Addr{}, false
	}
	h := int(p[0]&15) * 4
	if h < 20 || len(p) < h+4 || binary.BigEndian.Uint16(p[6:8])&0x1fff != 0 {
		return flow{}, netip.Addr{}, false
	}
	if p[9] != 6 && p[9] != 17 {
		return flow{}, netip.Addr{}, false
	}
	src := netip.AddrFrom4([4]byte(p[12:16]))
	dst := netip.AddrFrom4([4]byte(p[16:20]))
	return flow{int(p[9]), netip.AddrPortFrom(src, binary.BigEndian.Uint16(p[h:h+2])).String(), netip.AddrPortFrom(dst, binary.BigEndian.Uint16(p[h+2:h+4])).String()}, dst, true
}

// A reverse RST closes the local TCP endpoint even when Windows SetTcpEntry
// cannot delete its TCB. Use its last ACK as the peer sequence number.
func tcpResetReply(p []byte) []byte {
	if len(p) < 40 || p[0]>>4 != 4 || p[9] != 6 {
		return nil
	}
	h := int(p[0]&15) * 4
	if h < 20 || h+20 > len(p) || binary.BigEndian.Uint16(p[6:8])&0x3fff != 0 || p[h+13]&0x04 != 0 {
		return nil
	}
	r := make([]byte, 40)
	r[0], r[8], r[9] = 0x45, 64, 6
	binary.BigEndian.PutUint16(r[2:4], 40)
	copy(r[12:16], p[16:20])
	copy(r[16:20], p[12:16])
	copy(r[20:22], p[h+2:h+4])
	copy(r[22:24], p[h:h+2])
	r[32], r[33] = 0x50, 0x04
	if p[h+13]&0x10 != 0 {
		copy(r[24:28], p[h+8:h+12])
	} else if p[h+13]&0x02 != 0 {
		r[33] |= 0x10
		binary.BigEndian.PutUint32(r[28:32], binary.BigEndian.Uint32(p[h+4:h+8])+1)
	} else {
		return nil
	}
	binary.BigEndian.PutUint16(r[10:12], packetChecksum(r[:20], 0))
	pseudo := uint32(6 + 20)
	for i := 12; i < 20; i += 2 {
		pseudo += uint32(binary.BigEndian.Uint16(r[i : i+2]))
	}
	binary.BigEndian.PutUint16(r[36:38], packetChecksum(r[20:], pseudo))
	return r
}

func packetChecksum(b []byte, sum uint32) uint16 {
	for len(b) >= 2 {
		sum += uint32(binary.BigEndian.Uint16(b[:2]))
		b = b[2:]
	}
	if len(b) != 0 {
		sum += uint32(b[0]) << 8
	}
	for sum>>16 != 0 {
		sum = sum&0xffff + sum>>16
	}
	return ^uint16(sum)
}
