//go:build android

package main

import (
	"context"
	"fmt"
	"net"
	"strconv"
	"time"

	"github.com/pion/transport/v4"
)

// mobileNet — transport.Net без stdnet/anet (HarmonyOS и Android 11+ без netlink CAP).
type mobileNet struct{}

func (mobileNet) ListenPacket(network, address string) (net.PacketConn, error) {
	return net.ListenPacket(network, address)
}

func (mobileNet) ListenUDP(network string, locAddr *net.UDPAddr) (transport.UDPConn, error) {
	return net.ListenUDP(network, locAddr)
}

func (mobileNet) ListenTCP(network string, laddr *net.TCPAddr) (transport.TCPListener, error) {
	l, err := net.ListenTCP(network, laddr)
	if err != nil {
		return nil, err
	}
	return tcpListenerWrap{l}, nil
}

func (mobileNet) Dial(network, address string) (net.Conn, error) {
	return net.Dial(network, address)
}

func (mobileNet) DialUDP(network string, laddr, raddr *net.UDPAddr) (transport.UDPConn, error) {
	if laddr == nil {
		laddr = defaultLocalUDPAddr(raddr)
	}
	return net.DialUDP(network, laddr, raddr)
}

func (mobileNet) DialTCP(network string, laddr, raddr *net.TCPAddr) (transport.TCPConn, error) {
	return net.DialTCP(network, laddr, raddr)
}

func (mobileNet) ResolveIPAddr(network, address string) (*net.IPAddr, error) {
	return net.ResolveIPAddr(network, address)
}

func (mobileNet) ResolveUDPAddr(network, address string) (*net.UDPAddr, error) {
	return resolveUDPAddrNoRoute(network, address)
}

func (mobileNet) ResolveTCPAddr(network, address string) (*net.TCPAddr, error) {
	return net.ResolveTCPAddr(network, address)
}

func (mobileNet) Interfaces() ([]*transport.Interface, error) {
	return []*transport.Interface{}, nil
}

func (mobileNet) InterfaceByIndex(index int) (*transport.Interface, error) {
	return nil, fmt.Errorf("%w: index=%d", transport.ErrInterfaceNotFound, index)
}

func (mobileNet) InterfaceByName(name string) (*transport.Interface, error) {
	return nil, fmt.Errorf("%w: %s", transport.ErrInterfaceNotFound, name)
}

func (mobileNet) CreateDialer(d *net.Dialer) transport.Dialer {
	return stdDialerWrap{d}
}

func (mobileNet) CreateListenConfig(c *net.ListenConfig) transport.ListenConfig {
	return stdListenConfigWrap{c}
}

type stdDialerWrap struct{ *net.Dialer }

func (d stdDialerWrap) Dial(network, address string) (net.Conn, error) {
	return d.Dialer.Dial(network, address)
}

type stdListenConfigWrap struct{ *net.ListenConfig }

func (d stdListenConfigWrap) Listen(ctx context.Context, network, address string) (net.Listener, error) {
	return d.ListenConfig.Listen(ctx, network, address)
}

func (d stdListenConfigWrap) ListenPacket(ctx context.Context, network, address string) (net.PacketConn, error) {
	return d.ListenConfig.ListenPacket(ctx, network, address)
}

type tcpListenerWrap struct{ *net.TCPListener }

func (l tcpListenerWrap) AcceptTCP() (transport.TCPConn, error) {
	return l.TCPListener.AcceptTCP()
}

func defaultLocalUDPAddr(remote *net.UDPAddr) *net.UDPAddr {
	if remote != nil && remote.IP.To4() == nil && remote.IP.To16() != nil {
		return &net.UDPAddr{IP: net.IPv6zero, Port: 0}
	}
	return &net.UDPAddr{IP: net.IPv4zero, Port: 0}
}

func resolveUDPAddrNoRoute(network, address string) (*net.UDPAddr, error) {
	host, portStr, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return nil, err
	}
	ip := net.ParseIP(host)
	if ip == nil {
		ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
		defer cancel()
		ips, err := net.DefaultResolver.LookupIP(ctx, "ip", host)
		if err != nil {
			return nil, err
		}
		if len(ips) == 0 {
			return nil, fmt.Errorf("no IP addresses for %q", host)
		}
		ip = ips[0]
		for _, cand := range ips {
			if v4 := cand.To4(); v4 != nil {
				ip = v4
				break
			}
		}
	} else if v4 := ip.To4(); v4 != nil {
		ip = v4
	}
	return &net.UDPAddr{IP: ip, Port: port}, nil
}

func dialUDPForTURN(resolved *net.UDPAddr) (*net.UDPConn, error) {
	// Prefer physical Wi‑Fi/LTE iface so TURN не уходит в WG tunnel.
	if ip := getLanIPv4(); ip != nil {
		return net.DialUDP("udp", &net.UDPAddr{IP: ip}, resolved)
	}
	laddr := defaultLocalUDPAddr(resolved)
	return net.DialUDP("udp", laddr, resolved)
}
