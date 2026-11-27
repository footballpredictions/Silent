package main

import (
	"net"
	"time"
)

// Regular connects keep the system route. Only the recovery retry supplies an
// Android Network handle, without binding to an interface address.
func newVkDirectDialer() net.Dialer {
	return physicalTransportDialer(net.Dialer{
		Timeout:   20 * time.Second,
		KeepAlive: 30 * time.Second,
	}, bindPhysicalTransport)
}
