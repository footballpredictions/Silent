//go:build linux

package main

import (
	"net"
	"os"
	"strings"
	"syscall"
)

// Как Android VpnService.protect(): fwmark → policy routing мимо WG (helper protect-on).
// Нужны cap_net_admin,cap_net_raw на wdtt-client (setcap в .deb postinst).
const lanProtectMark = 0x53494c // 'SIL'

func applyLanIfaceBind(d *net.Dialer) {
	if d == nil {
		return
	}
	iface := strings.TrimSpace(os.Getenv("SILENT_LAN_IFACE"))
	prev := d.Control
	d.Control = func(network, address string, c syscall.RawConn) error {
		if prev != nil {
			if err := prev(network, address, c); err != nil {
				return err
			}
		}
		return setLanSocketOpts(c, iface)
	}
}

func applyLanConnProtect(conn syscall.Conn) {
	if conn == nil {
		return
	}
	raw, err := conn.SyscallConn()
	if err != nil || raw == nil {
		return
	}
	iface := strings.TrimSpace(os.Getenv("SILENT_LAN_IFACE"))
	_ = setLanSocketOpts(raw, iface)
}

func setLanSocketOpts(c syscall.RawConn, iface string) error {
	var opErr error
	err := c.Control(func(fd uintptr) {
		// SO_MARK: весь TURN/VK auth WDTT идёт в table protect (не в wg-turn).
		if e := syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_MARK, lanProtectMark); e != nil {
			opErr = e
		}
		if iface != "" && len(iface) < syscall.IFNAMSIZ {
			if e := syscall.BindToDevice(int(fd), iface); e != nil && opErr == nil {
				opErr = e
			}
		}
	})
	if err != nil {
		return err
	}
	return opErr
}
