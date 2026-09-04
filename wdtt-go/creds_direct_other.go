//go:build !linux

package main

import (
	"net"
	"syscall"
)

func applyLanIfaceBind(_ *net.Dialer) {}

func applyLanConnProtect(_ syscall.Conn) {}
