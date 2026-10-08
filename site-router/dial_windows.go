package main

import (
	"net"
	"time"
)

type netDialer = net.Dialer

func newPhysicalDialer(timeout time.Duration) *net.Dialer {
	return &net.Dialer{Timeout: timeout, Control: bindPhysical}
}
