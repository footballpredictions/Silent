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
