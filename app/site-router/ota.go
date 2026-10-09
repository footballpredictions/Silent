//go:build linux || android

package main

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"sync/atomic"
	"time"

	"gvisor.dev/gvisor/pkg/buffer"
	"gvisor.dev/gvisor/pkg/tcpip"
	"gvisor.dev/gvisor/pkg/tcpip/adapters/gonet"
	"gvisor.dev/gvisor/pkg/tcpip/header"
	"gvisor.dev/gvisor/pkg/tcpip/link/channel"
	"gvisor.dev/gvisor/pkg/tcpip/network/ipv4"
	"gvisor.dev/gvisor/pkg/tcpip/stack"
	"gvisor.dev/gvisor/pkg/tcpip/transport/tcp"
)

// TCP for two read-only OTA endpoints over the ALREADY running WireGuard device.
// No second WG handshake/key, Android bind, overlay, or application route change.
type otaStack struct {
	stack   *stack.Stack
	link    *channel.Endpoint
	address tcpip.Address
	gateway tcpip.Address
	port    uint16
	next    atomic.Uint32
	active  sync.Map
}

func newOTAStack(ctx context.Context, address string, mtu int, write func([]byte) error) (*otaStack, error) {
	ip := net.ParseIP(address).To4()
	if ip == nil {
		return nil, errors.New("OTA requires IPv4 WG address")
	}
	s := stack.New(stack.Options{NetworkProtocols: []stack.NetworkProtocolFactory{ipv4.NewProtocol}, TransportProtocols: []stack.TransportProtocolFactory{tcp.NewProtocol}})
	link := channel.New(128, uint32(mtu), "")
	if err := s.CreateNIC(1, link); err != nil {
		s.Close()
		return nil, errors.New(err.String())
	}
	local := tcpip.AddrFrom4Slice(ip)
	if err := s.AddProtocolAddress(1, tcpip.ProtocolAddress{Protocol: ipv4.ProtocolNumber,
		AddressWithPrefix: tcpip.AddressWithPrefix{Address: local, PrefixLen: 32}}, stack.AddressProperties{}); err != nil {
		s.Close()
		return nil, errors.New(err.String())
	}
	s.SetRouteTable([]tcpip.Route{{Destination: header.IPv4EmptySubnet, NIC: 1}})
	o := &otaStack{stack: s, link: link, address: local, gateway: tcpip.AddrFrom4([4]byte{10, 66, 66, 1}), port: 8000}
	go func() {
		for {
			packet := link.ReadContext(ctx)
			if packet == nil {
				return
			}
			view := packet.ToView()
			raw := append([]byte(nil), view.AsSlice()...)
			view.Release()
			packet.DecRef()
			if write(raw) != nil {
				return
			}
		}
	}()
	return o, nil
}

type otaConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *otaConn) Close() error { err := c.Conn.Close(); c.once.Do(c.release); return err }

func (o *otaStack) dial(ctx context.Context, _, target string) (net.Conn, error) {
	if target != net.JoinHostPort(o.gateway.String(), fmt.Sprint(o.port)) {
		return nil, errors.New("OTA target rejected")
	}
	// Below Android's ephemeral range. Only active exact API tuples are intercepted.
	for attempt := 0; attempt < 128; attempt++ {
		port := uint16(23000 + o.next.Add(1)%128)
		if _, used := o.active.LoadOrStore(port, true); used {
			continue
		}
		conn, err := gonet.DialTCPWithBind(ctx, o.stack,
			tcpip.FullAddress{NIC: 1, Addr: o.address, Port: port},
			tcpip.FullAddress{NIC: 1, Addr: o.gateway, Port: o.port}, ipv4.ProtocolNumber)
		if err != nil {
			o.active.Delete(port)
			return nil, err
		}
		return &otaConn{Conn: conn, release: func() { o.active.Delete(port) }}, nil
	}
	return nil, errors.New("OTA connection limit")
}

func (o *otaStack) receive(packet []byte) bool {
	if o == nil || len(packet) < 40 || packet[0]>>4 != 4 || packet[9] != 6 {
		return false
	}
	h := int(packet[0]&15) * 4
	if h < 20 || len(packet) < h+20 {
		return false
	}
	if tcpip.AddrFrom4Slice(packet[12:16]) != o.gateway || tcpip.AddrFrom4Slice(packet[16:20]) != o.address {
		return false
	}
	source := uint16(packet[h])<<8 | uint16(packet[h+1])
	port := uint16(packet[h+2])<<8 | uint16(packet[h+3])
	if source != o.port {
		return false
	}
	if _, active := o.active.Load(port); !active {
		return false
	}
	p := stack.NewPacketBuffer(stack.PacketBufferOptions{Payload: buffer.MakeWithData(append([]byte(nil), packet...))})
	o.link.InjectInbound(ipv4.ProtocolNumber, p)
	p.DecRef()
	return true
}

func tcpipSourceIsOTA(o *otaStack, packet []byte) bool {
	if len(packet) < 40 || packet[0]>>4 != 4 || packet[9] != 6 {
		return false
	}
	h := int(packet[0]&15) * 4
	if h < 20 || len(packet) < h+20 || tcpip.AddrFrom4Slice(packet[12:16]) != o.address || tcpip.AddrFrom4Slice(packet[16:20]) != o.gateway {
		return false
	}
	port := uint16(packet[h])<<8 | uint16(packet[h+1])
	remote := uint16(packet[h+2])<<8 | uint16(packet[h+3])
	_, active := o.active.Load(port)
	return active && remote == o.port
}

func otaHandler(transport http.RoundTripper) http.Handler {
	upstream, _ := url.Parse("http://10.66.66.1:8000")
	proxy := httputil.NewSingleHostReverseProxy(upstream)
	proxy.Transport = transport
	proxy.FlushInterval = -1
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || (r.URL.Path != "/api/updates/check" && r.URL.Path != "/api/updates/download/android") {
			http.Error(w, "OTA endpoint only", http.StatusForbidden)
			return
		}
		proxy.ServeHTTP(w, r)
	})
}

func (o *otaStack) serve(port int) (*http.Server, error) {
	listener, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return nil, err
	}
	transport := &http.Transport{DialContext: o.dial, MaxIdleConns: 2, IdleConnTimeout: 30 * time.Second,
		ResponseHeaderTimeout: 15 * time.Second, DisableCompression: true}
	server := &http.Server{Handler: otaHandler(transport), ReadHeaderTimeout: 5 * time.Second}
	go server.Serve(listener)
	return server, nil
}
