package main

import (
	"log"
	"net"
	"sync"
	"syscall"
)

// Set once by the Android executable, only for the network recovery retry.
var bindPhysicalTransport func(uintptr) error
var physicalBindWarning sync.Once

func physicalTransportDialer(dialer net.Dialer, bind func(uintptr) error) net.Dialer {
	if bind == nil {
		return dialer
	}
	dialer.Control = func(_, address string, raw syscall.RawConn) error {
		host, _, err := net.SplitHostPort(address)
		if err != nil {
			return err
		}
		ip := net.ParseIP(host)
		if ip == nil || ip.IsLoopback() {
			return nil
		}
		return raw.Control(func(fd uintptr) {
			if err := bind(fd); err != nil {
				// Android can retire the Network while a dial is being created.
				// A new socket can still use the newly selected default.
				physicalBindWarning.Do(func() { log.Printf("[NETWORK] Physical socket binding unavailable: %v", err) })
			}
		})
	}
	return dialer
}
