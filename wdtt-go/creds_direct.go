package main

import (
	"context"
	"net"
	"strings"
	"sync"
	"time"
)

var (
	lanIPv4Mu sync.Mutex
	lanIPv4   net.IP
)

// Публичные DNS — обход DPI/poison Wi‑Fi ISP, который ломает api.vk.me.
var vkPublicDNSServers = []string{
	"8.8.8.8:53",
	"77.88.8.8:53",
	"1.1.1.1:53",
}

func isVirtualIface(name string) bool {
	n := strings.ToLower(name)
	for _, bad := range []string{
		"vethernet", "hyper-v", "wsl", "docker", "vmware", "virtualbox",
		"wireguard", "wg-turn", "nordlynx", "tun", "tap", "npf", "loopback",
		"bluetooth", "pseudo", "default switch",
	} {
		if strings.Contains(n, bad) {
			return true
		}
	}
	return false
}

func isUsableLanIPv4(ip net.IP) bool {
	ip4 := ip.To4()
	if ip4 == nil || ip4.IsLoopback() || ip4.IsLinkLocalUnicast() {
		return false
	}
	// WireGuard Silent
	if ip4[0] == 10 && ip4[1] == 66 {
		return false
	}
	// WSL / Hyper-V (172.16–172.31)
	if ip4[0] == 172 && ip4[1] >= 16 && ip4[1] <= 31 {
		return false
	}
	if ip4[0] == 169 && ip4[1] == 254 {
		return false
	}
	return true
}

func scoreLanIPv4(ip net.IP) int {
	ip4 := ip.To4()
	if ip4 == nil {
		return -1
	}
	if ip4[0] == 192 && ip4[1] == 168 {
		return 100
	}
	if ip4[0] == 10 {
		return 50
	}
	return 10
}

// detectOutboundIPv4 — IP по таблице маршрутизации (реальный выход в интернет).
func detectOutboundIPv4() net.IP {
	conn, err := net.DialTimeout("udp4", "8.8.8.8:53", 2*time.Second)
	if err != nil {
		conn, err = net.DialTimeout("udp4", "77.88.8.8:53", 2*time.Second)
	}
	if err != nil {
		return nil
	}
	defer conn.Close()
	ua, ok := conn.LocalAddr().(*net.UDPAddr)
	if !ok || !isUsableLanIPv4(ua.IP) {
		return nil
	}
	return ua.IP.To4()
}

func pickLanFromInterfaces() net.IP {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var best net.IP
	bestScore := -1
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		if isVirtualIface(iface.Name) {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			ip4 := ipnet.IP.To4()
			if !isUsableLanIPv4(ip4) {
				continue
			}
			s := scoreLanIPv4(ip4)
			if s > bestScore {
				bestScore = s
				best = ip4
			}
		}
	}
	return best
}

// getLanIPv4 — Wi‑Fi/Ethernet, не WG и не vEthernet/WSL.
func getLanIPv4() net.IP {
	lanIPv4Mu.Lock()
	defer lanIPv4Mu.Unlock()

	if ip := detectOutboundIPv4(); ip != nil {
		lanIPv4 = ip
		return lanIPv4
	}
	if ip := pickLanFromInterfaces(); ip != nil {
		lanIPv4 = ip
		return lanIPv4
	}
	lanIPv4 = nil
	return nil
}

func lanBoundDialer(timeout time.Duration) *net.Dialer {
	return &net.Dialer{
		Timeout:   timeout,
		KeepAlive: 30 * time.Second,
	}
}

func dialViaLan(ctx context.Context, network, address string, timeout time.Duration) (net.Conn, error) {
	d := lanBoundDialer(timeout)
	ip := getLanIPv4()
	if ip != nil {
		switch network {
		case "udp", "udp4":
			d.LocalAddr = &net.UDPAddr{IP: ip}
		default:
			d.LocalAddr = &net.TCPAddr{IP: ip}
		}
	}
	return d.DialContext(ctx, network, address)
}

func newVkDirectDialer() net.Dialer {
	d := net.Dialer{
		Timeout:   20 * time.Second,
		KeepAlive: 30 * time.Second,
		Resolver:  vkDirectResolver(),
	}
	if ip := getLanIPv4(); ip != nil {
		d.LocalAddr = &net.TCPAddr{IP: ip}
	}
	return d
}

// vkDirectResolver — DNS только на публичные резолверы (не ISP), с LAN-bind.
// Раньше Dial игнорировал адрес и ходил на system DNS → Wi‑Fi DPI poison api.vk.me.
func vkDirectResolver() *net.Resolver {
	return &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
			var lastErr error
			for _, dnsAddr := range vkPublicDNSServers {
				conn, err := dialViaLan(ctx, network, dnsAddr, 3*time.Second)
				if err == nil {
					return conn, nil
				}
				lastErr = err
			}
			if lastErr == nil {
				lastErr = net.UnknownNetworkError(network)
			}
			return nil, lastErr
		},
	}
}

// dialTurnUDP — TURN с LocalAddr = Wi‑Fi/Ethernet (не wg-turn).
func dialTurnUDP(resolved *net.UDPAddr) (*net.UDPConn, error) {
	var laddr *net.UDPAddr
	if ip := getLanIPv4(); ip != nil {
		laddr = &net.UDPAddr{IP: ip}
	}
	return net.DialUDP("udp", laddr, resolved)
}
