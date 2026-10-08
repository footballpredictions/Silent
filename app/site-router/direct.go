//go:build linux || android

package main

import (
	"context"
	"io"
	"net"
	"time"

	"gvisor.dev/gvisor/pkg/buffer"
	"gvisor.dev/gvisor/pkg/tcpip"
	"gvisor.dev/gvisor/pkg/tcpip/adapters/gonet"
	"gvisor.dev/gvisor/pkg/tcpip/header"
	"gvisor.dev/gvisor/pkg/tcpip/link/channel"
	"gvisor.dev/gvisor/pkg/tcpip/network/ipv4"
	"gvisor.dev/gvisor/pkg/tcpip/stack"
	"gvisor.dev/gvisor/pkg/tcpip/transport/tcp"
	"gvisor.dev/gvisor/pkg/tcpip/transport/udp"
	"gvisor.dev/gvisor/pkg/waiter"
)

// The router process belongs to Silent's excluded UID: these outbound sockets
// use the physical network. Application flows never enter this TCP/IP stack.
type directStack struct {
	stack *stack.Stack
	link  *channel.Endpoint
}

type idleConn struct{ net.Conn }

func (c idleConn) Read(b []byte) (int, error) {
	c.SetReadDeadline(time.Now().Add(5 * time.Minute))
	return c.Conn.Read(b)
}
func (c idleConn) Write(b []byte) (int, error) {
	c.SetWriteDeadline(time.Now().Add(5 * time.Minute))
	return c.Conn.Write(b)
}

func newDirectStack(ctx context.Context, mtu int, write func([]byte) error) *directStack {
	s := stack.New(stack.Options{NetworkProtocols: []stack.NetworkProtocolFactory{ipv4.NewProtocol}, TransportProtocols: []stack.TransportProtocolFactory{tcp.NewProtocol, udp.NewProtocol}})
	link := channel.New(512, uint32(mtu), "")
	if err := s.CreateNIC(1, link); err != nil {
		panic(err.String())
	}
	s.SetPromiscuousMode(1, true)
	s.SetSpoofing(1, true)
	s.SetRouteTable([]tcpip.Route{{Destination: header.IPv4EmptySubnet, NIC: 1}})
	tcpForwarder := tcp.NewForwarder(s, 65535, 256, func(request *tcp.ForwarderRequest) {
		go func() {
			id := request.ID()
			target := net.JoinHostPort(id.LocalAddress.String(), portString(id.LocalPort))
			upstream, err := (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, "tcp4", target)
			if err != nil {
				request.Complete(true)
				return
			}
			var queue waiter.Queue
			endpoint, epErr := request.CreateEndpoint(&queue)
			if epErr != nil {
				upstream.Close()
				request.Complete(true)
				return
			}
			request.Complete(false)
			client := gonet.NewTCPConn(&queue, endpoint)
			defer client.Close()
			defer upstream.Close()
			done := make(chan struct{})
			go func() {
				io.Copy(idleConn{upstream}, idleConn{client})
				if c, ok := upstream.(*net.TCPConn); ok {
					c.CloseWrite()
				}
				close(done)
			}()
			io.Copy(idleConn{client}, idleConn{upstream})
			client.CloseWrite()
			<-done
		}()
	})
	s.SetTransportProtocolHandler(tcp.ProtocolNumber, tcpForwarder.HandlePacket)
	udpForwarder := udp.NewForwarder(s, func(request *udp.ForwarderRequest) {
		id := request.ID()
		var queue waiter.Queue
		endpoint, err := request.CreateEndpoint(&queue)
		if err != nil {
			return
		}
		client := gonet.NewUDPConn(&queue, endpoint)
		go func() {
			defer client.Close()
			upstream, err := (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "udp4", net.JoinHostPort(id.LocalAddress.String(), portString(id.LocalPort)))
			if err != nil {
				return
			}
			defer upstream.Close()
			done := make(chan struct{})
			go func() {
				defer close(done)
				packet := make([]byte, 65535)
				for {
					client.SetReadDeadline(time.Now().Add(45 * time.Second))
					n, e := client.Read(packet)
					if e != nil {
						return
					}
					if _, e = upstream.Write(packet[:n]); e != nil {
						return
					}
				}
			}()
			packet := make([]byte, 65535)
			for {
				upstream.SetReadDeadline(time.Now().Add(45 * time.Second))
				n, e := upstream.Read(packet)
				if e != nil {
					break
				}
				if _, e = client.Write(packet[:n]); e != nil {
					break
				}
			}
			client.Close()
			<-done
		}()
	})
	s.SetTransportProtocolHandler(udp.ProtocolNumber, udpForwarder.HandlePacket)
	go func() {
		for {
			packet := link.ReadContext(ctx)
			if packet == nil {
				return
			}
			view := packet.ToView()
			write(view.AsSlice())
			view.Release()
			packet.DecRef()
		}
	}()
	go func() { <-ctx.Done(); s.Close(); link.Close() }()
	return &directStack{s, link}
}

func (s *directStack) inject(packet []byte) {
	b := stack.NewPacketBuffer(stack.PacketBufferOptions{Payload: buffer.MakeWithData(packet)})
	s.link.InjectInbound(header.IPv4ProtocolNumber, b)
	b.DecRef()
}
