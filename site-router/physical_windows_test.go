package main

import (
	"net"
	"net/netip"
	"testing"
)

func preparePhysicalTest(t *testing.T, host string) {
	t.Helper()
	interfaces, _ := net.Interfaces()
	for _, iface := range interfaces {
		addresses, _ := iface.Addrs()
		for _, a := range addresses {
			p, e := netip.ParsePrefix(a.String())
			if e == nil && p.Addr().String() == host {
				physicalIndex = uint32(iface.Index)
				t.Cleanup(func() { physicalIndex = 0 })
				return
			}
		}
	}
	t.Fatal("physical interface not found")
}
