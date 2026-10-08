//go:build windows || linux || android

package main

import (
	"context"
	"io"
	"net"
	"net/netip"
	"testing"
	"time"

	"golang.zx2c4.com/wireguard/tun/netstack"
)

func TestDirectBrowserStackTCPAndUDPReplies(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	clientTun, client, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.0.0.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	defer clientTun.Close()
	direct := newDirectStack(ctx, 1200, func(p []byte) error { _, err := clientTun.Write([][]byte{append([]byte(nil), p...)}, 0); return err })
	go func() {
		b := [][]byte{make([]byte, 65535)}
		sizes := make([]int, 1)
		for {
			_, err := clientTun.Read(b, sizes, 0)
			if err != nil {
				return
			}
			direct.inject(append([]byte(nil), b[0][:sizes[0]]...))
		}
	}()

	host := ""
	addresses, _ := net.InterfaceAddrs()
	for _, address := range addresses {
		prefix, e := netip.ParsePrefix(address.String())
		if e == nil && prefix.Addr().Is4() && !prefix.Addr().IsLoopback() && !prefix.Addr().IsLinkLocalUnicast() {
			host = prefix.Addr().String()
			break
		}
	}
	if host == "" {
		t.Skip("physical IPv4 address unavailable")
	}
	preparePhysicalTest(t, host)
	tcpServer, err := net.Listen("tcp4", "0.0.0.0:0")
	if err != nil {
		t.Fatal(err)
	}
	defer tcpServer.Close()
	go func() {
		c, e := tcpServer.Accept()
		if e != nil {
			return
		}
		defer c.Close()
		io.Copy(c, c)
	}()
	tcpContext, stopTCP := context.WithTimeout(ctx, 5*time.Second)
	defer stopTCP()
	tcpClient, err := client.DialContextTCPAddrPort(tcpContext, netip.MustParseAddrPort(net.JoinHostPort(host, portString(uint16(tcpServer.Addr().(*net.TCPAddr).Port)))))
	if err != nil {
		t.Fatal("direct browser TCP dial:", err)
	}
	defer tcpClient.Close()
	tcpClient.SetDeadline(time.Now().Add(5 * time.Second))
	tcpClient.Write([]byte("browser TCP"))
	b := make([]byte, 11)
	if _, err := io.ReadFull(tcpClient, b); err != nil || string(b) != "browser TCP" {
		t.Fatalf("TCP reply %q %v", b, err)
	}

	udpServer, err := net.ListenPacket("udp4", "0.0.0.0:0")
	if err != nil {
		t.Fatal(err)
	}
	defer udpServer.Close()
	go func() {
		b := make([]byte, 100)
		for {
			n, peer, e := udpServer.ReadFrom(b)
			if e != nil {
				return
			}
			udpServer.WriteTo(b[:n], peer)
		}
	}()
	udpClient, err := client.DialUDPAddrPort(netip.AddrPort{}, netip.MustParseAddrPort(net.JoinHostPort(host, portString(uint16(udpServer.LocalAddr().(*net.UDPAddr).Port)))))
	if err != nil {
		t.Fatal(err)
	}
	defer udpClient.Close()
	udpClient.SetDeadline(time.Now().Add(5 * time.Second))
	udpClient.Write([]byte("browser UDP"))
	n, err := udpClient.Read(b)
	if err != nil || string(b[:n]) != "browser UDP" {
		t.Fatalf("UDP reply %q %v", b[:n], err)
	}
	var tcpFlow flow
	direct.mu.Lock()
	for f := range direct.flows {
		if f.Protocol == 6 {
			tcpFlow = f
			break
		}
	}
	direct.mu.Unlock()
	if tcpFlow.Protocol != 6 {
		t.Fatal("active direct TCP flow was not tracked")
	}
	direct.closeFlow(tcpFlow)
	tcpClient.SetReadDeadline(time.Now().Add(time.Second))
	if _, e := tcpClient.Read(b); e == nil {
		t.Fatal("changed direct connection was not closed")
	} else if timeout, ok := e.(net.Error); ok && timeout.Timeout() {
		t.Fatal("closing direct connection timed out")
	}
	udpClient.Write([]byte("browser UDP"))
	n, err = udpClient.Read(b)
	if err != nil || string(b[:n]) != "browser UDP" {
		t.Fatalf("unrelated UDP flow was closed: %v", err)
	}
}
