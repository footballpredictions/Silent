package main

import (
	"net"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

func newPhysicalDialer(timeout time.Duration) *net.Dialer {
	return &net.Dialer{Timeout: timeout, Control: func(network, address string, raw syscall.RawConn) error {
		if physicalIndex == 0 {
			return nil
		}
		var socketErr error
		err := raw.Control(func(fd uintptr) {
			socketErr = unix.SetsockoptInt(int(fd), unix.IPPROTO_IP, unix.IP_BOUND_IF, int(physicalIndex))
		})
		if err != nil {
			return err
		}
		return socketErr
	}}
}

func physicalDialer(timeout time.Duration) *net.Dialer { return newPhysicalDialer(timeout) }
