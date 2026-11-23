//go:build !windows

package main

import "net"

func vkAdapterDNS(net.IP) []string { return nil }
