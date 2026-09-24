//go:build !linux && !darwin

package main

import (
	"net"
	"syscall"
)

func logLanProtectBanner() {}

func applyLanIfaceBind(_ *net.Dialer) {}

func applyLanConnProtect(_ syscall.Conn) {}
