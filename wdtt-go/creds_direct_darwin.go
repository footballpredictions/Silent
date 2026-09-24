//go:build darwin

package main

import (
	"log"
	"net"
	"os"
	"strings"
	"sync/atomic"
	"syscall"

	"golang.org/x/sys/unix"
)

// Как iOS Network Extension / Android VpnService.protect() / Linux SO_MARK:
// сокеты TURN/VK auth WDTT должны уходить в физ. iface, иначе после
// 0.0.0.0/1→utun весь uplink WDTT заворачивается в тот же WG (rx=handshake only).
// На Darwin нет SO_MARK → IP_BOUND_IF + LocalAddr (см. dialViaLan).

// logLanProtectBanner — сразу при старте, до dial: в Desktop-логе видно,
// что бинарь с IP_BOUND_IF (старый wdtt без этой строки → full /1 убивает hive).
func logLanProtectBanner() {
	idx := darwinLanIfIndex()
	name := strings.TrimSpace(os.Getenv("SILENT_LAN_IFACE"))
	if name == "" {
		name = "?"
	}
	if idx <= 0 {
		log.Printf("[LAN] protect=darwin IP_BOUND_IF NOT ready (iface=%s ifindex=0) — TURN уйдёт в utun после 0/1", name)
		return
	}
	log.Printf("[LAN] protect=darwin IP_BOUND_IF ready ifindex=%d iface=%s (WDTT мимо utun)", idx, name)
}

func applyLanIfaceBind(d *net.Dialer) {
	if d == nil {
		return
	}
	prev := d.Control
	d.Control = func(network, address string, c syscall.RawConn) error {
		if prev != nil {
			if err := prev(network, address, c); err != nil {
				return err
			}
		}
		return setDarwinBoundIf(c)
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
	_ = setDarwinBoundIf(raw)
}

func setDarwinBoundIf(c syscall.RawConn) error {
	idx := darwinLanIfIndex()
	if idx <= 0 {
		return nil
	}
	var opErr error
	err := c.Control(func(fd uintptr) {
		if e := unix.SetsockoptInt(int(fd), unix.IPPROTO_IP, unix.IP_BOUND_IF, idx); e != nil {
			opErr = e
		}
	})
	if err != nil {
		return err
	}
	if opErr == nil {
		darwinBoundIfLogOnce(idx)
	}
	return opErr
}

var darwinBoundIfLogged uint32

func darwinBoundIfLogOnce(idx int) {
	if !atomic.CompareAndSwapUint32(&darwinBoundIfLogged, 0, 1) {
		return
	}
	name := strings.TrimSpace(os.Getenv("SILENT_LAN_IFACE"))
	if name == "" {
		name = "?"
	}
	log.Printf("[LAN] IP_BOUND_IF ifindex=%d iface=%s (WDTT мимо utun)", idx, name)
}

func darwinLanIfIndex() int {
	name := strings.TrimSpace(os.Getenv("SILENT_LAN_IFACE"))
	if name != "" {
		ifi, err := net.InterfaceByName(name)
		if err == nil && ifi != nil && ifi.Index > 0 {
			return ifi.Index
		}
	}
	ip := getLanIPv4()
	if ip == nil {
		return 0
	}
	ifaces, err := net.Interfaces()
	if err != nil {
		return 0
	}
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		n := strings.ToLower(iface.Name)
		if strings.HasPrefix(n, "utun") || strings.HasPrefix(n, "awdl") || strings.HasPrefix(n, "llw") {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			var cand net.IP
			switch v := a.(type) {
			case *net.IPNet:
				cand = v.IP
			case *net.IPAddr:
				cand = v.IP
			}
			if cand != nil && cand.Equal(ip) {
				return iface.Index
			}
		}
	}
	return 0
}
