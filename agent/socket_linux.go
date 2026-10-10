package main

import (
	"golang.org/x/sys/unix"
	"net"
	"syscall"
	"time"
)

func boundDialer(ip string, tcp bool) *net.Dialer {
	d := &net.Dialer{Timeout: 3 * time.Second, Control: func(network, address string, c syscall.RawConn) error {
		var sockErr error
		err := c.Control(func(fd uintptr) {
			sockErr = unix.SetsockoptString(int(fd), unix.SOL_SOCKET, unix.SO_BINDTODEVICE, iface)
		})
		if err != nil {
			return err
		}
		return sockErr
	}}
	if tcp {
		d.LocalAddr = &net.TCPAddr{IP: net.ParseIP(ip)}
	} else {
		d.LocalAddr = &net.UDPAddr{IP: net.ParseIP(ip)}
	}
	return d
}
