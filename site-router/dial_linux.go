package main

import (
	"net"
	"time"
)

func physicalDialer(timeout time.Duration) *net.Dialer { return &net.Dialer{Timeout: timeout} }
