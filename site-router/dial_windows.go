package main

import (
	"net"
	"time"
)

func runUnix() error { panic("unsupported platform") }

type netDialer = net.Dialer

func newPhysicalDialer(timeout time.Duration) *net.Dialer {
	return &net.Dialer{Timeout: timeout, Control: bindPhysical}
}
