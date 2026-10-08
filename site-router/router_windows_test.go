package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"golang.org/x/crypto/curve25519"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
	"io"
	"net"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestWindowsTCPAndUDPProcessOwner(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	client, err := net.Dial("tcp4", listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	server, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	f := flow{Protocol: 6, Local: client.LocalAddr().String(), Remote: client.RemoteAddr().String()}
	if pid := ownerPID(f); pid != uint32(os.Getpid()) {
		t.Fatalf("TCP owner %d, want %d", pid, os.Getpid())
	}
	udp, err := net.ListenPacket("udp4", "0.0.0.0:0")
	if err != nil {
		t.Fatal(err)
	}
	defer udp.Close()
	f = flow{Protocol: 17, Local: net.JoinHostPort("127.0.0.1", portString(uint16(udp.LocalAddr().(*net.UDPAddr).Port))), Remote: "127.0.0.1:443"}
	if pid := ownerPID(f); pid != uint32(os.Getpid()) {
		t.Fatalf("UDP owner %d, want %d", pid, os.Getpid())
	}
	if processExe(uint32(os.Getpid())) == "" {
		t.Fatal("process path missing")
	}
}

func TestWindowsParseConfigNeverUsesWgQuickKeysInUAPI(t *testing.T) {
	key := base64.StdEncoding.EncodeToString(make([]byte, 32))
	text := "[Interface]\nPrivateKey = " + key + "\nAddress = 10.0.0.2/32\nDNS = 1.1.1.1\nMTU = 1420\n[Peer]\nPublicKey = " + key + "\nAllowedIPs = 0.0.0.0/1, 128.0.0.0/1\nEndpoint = 127.0.0.1:9000\nPersistentKeepalive = 25\n"
	ipc, address, mtu, err := parseConfig(text)
	if err != nil {
		t.Fatal(err)
	}
	if address != "10.0.0.2" || mtu != 1420 || strings.Contains(ipc, "DNS") || strings.Contains(ipc, "Address") || !strings.Contains(ipc, "allowed_ip=128.0.0.0/1") {
		t.Fatal("invalid UAPI conversion")
	}
}

func TestApplicationTrafficStillCrossesWireGuardWithEmptyBrowserAllowlist(t *testing.T) {
	// Real encrypted WG pair and TCP echo, entirely in memory; no OS routes changed.
	serverTun, serverNet, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.0.0.1")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	serverWG := device.NewDevice(serverTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	defer serverWG.Close()
	key := func() (string, string) {
		b := make([]byte, 32)
		rand.Read(b)
		pub, _ := curve25519.X25519(b, curve25519.Basepoint)
		return hex.EncodeToString(b), hex.EncodeToString(pub)
	}
	serverKey, serverPub := key()
	clientKey, clientPub := key()
	if err = serverWG.IpcSet("private_key=" + serverKey + "\nlisten_port=0\npublic_key=" + clientPub + "\nallowed_ip=10.0.0.2/32\n"); err != nil {
		t.Fatal(err)
	}
	if err = serverWG.Up(); err != nil {
		t.Fatal(err)
	}
	state, _ := serverWG.IpcGet()
	port := ""
	for _, line := range strings.Split(state, "\n") {
		if strings.HasPrefix(line, "listen_port=") {
			port = strings.TrimPrefix(line, "listen_port=")
		}
	}
	if n, _ := strconv.Atoi(port); n == 0 {
		t.Fatal("WG listen port missing")
	}
	clientTun, clientNet, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.0.0.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	routed := &routedTun{Device: clientTun, routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), owner: func(flow) string { return "C:\\Games\\game.exe" }}
	routed.policy.Store(newProcessPolicy(policyConfig{Whitelist: true}))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	routed.direct = newDirectStack(ctx, 1200, routed.writePacket)
	clientWG := device.NewDevice(routed, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	defer clientWG.Close()
	if err = clientWG.IpcSet("private_key=" + clientKey + "\npublic_key=" + serverPub + "\nendpoint=127.0.0.1:" + port + "\nallowed_ip=0.0.0.0/0\n"); err != nil {
		t.Fatal(err)
	}
	if err = clientWG.Up(); err != nil {
		t.Fatal(err)
	}
	listener, err := serverNet.ListenTCPAddrPort(netip.MustParseAddrPort("10.0.0.1:8443"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		c, e := listener.Accept()
		if e == nil {
			defer c.Close()
			io.Copy(c, c)
		}
	}()
	dialCtx, stop := context.WithTimeout(ctx, 5*time.Second)
	defer stop()
	c, err := clientNet.DialContextTCPAddrPort(dialCtx, netip.MustParseAddrPort("10.0.0.1:8443"))
	if err != nil {
		t.Fatal("application lost VPN with site allowlist:", err)
	}
	defer c.Close()
	c.SetDeadline(time.Now().Add(5 * time.Second))
	c.Write([]byte("application VPN"))
	b := make([]byte, 15)
	if _, err = io.ReadFull(c, b); err != nil || string(b) != "application VPN" {
		t.Fatalf("application echo %q: %v", b, err)
	}
}

func TestIdleBrowserConnectionClosesOnModeChangeWhenSetTCPEntryFails(t *testing.T) {
	// Real encrypted WG pair and TCP echo, entirely in memory; no OS routes changed.
	serverTun, serverNet, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.0.0.1")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	serverWG := device.NewDevice(serverTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	defer serverWG.Close()
	key := func() (string, string) {
		b := make([]byte, 32)
		rand.Read(b)
		pub, _ := curve25519.X25519(b, curve25519.Basepoint)
		return hex.EncodeToString(b), hex.EncodeToString(pub)
	}
	serverKey, serverPub := key()
	clientKey, clientPub := key()
	if err = serverWG.IpcSet("private_key=" + serverKey + "\nlisten_port=0\npublic_key=" + clientPub + "\nallowed_ip=10.0.0.2/32\n"); err != nil {
		t.Fatal(err)
	}
	if err = serverWG.Up(); err != nil {
		t.Fatal(err)
	}
	state, _ := serverWG.IpcGet()
	port := ""
	for _, line := range strings.Split(state, "\n") {
		if strings.HasPrefix(line, "listen_port=") {
			port = strings.TrimPrefix(line, "listen_port=")
		}
	}
	if n, _ := strconv.Atoi(port); n == 0 {
		t.Fatal("WG listen port missing")
	}
	clientTun, clientNet, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.0.0.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	routed := &routedTun{Device: clientTun, routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), owner: func(flow) string { return "chrome.exe" }}
	routed.policy.Store(newProcessPolicy(policyConfig{Whitelist: true, Targets: []string{"10.0.0.1/32"}}))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	routed.direct = newDirectStack(ctx, 1200, routed.writePacket)
	clientWG := device.NewDevice(routed, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	defer clientWG.Close()
	if err = clientWG.IpcSet("private_key=" + clientKey + "\npublic_key=" + serverPub + "\nendpoint=127.0.0.1:" + port + "\nallowed_ip=0.0.0.0/0\n"); err != nil {
		t.Fatal(err)
	}
	if err = clientWG.Up(); err != nil {
		t.Fatal(err)
	}
	listener, err := serverNet.ListenTCPAddrPort(netip.MustParseAddrPort("10.0.0.1:8443"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		c, e := listener.Accept()
		if e == nil {
			defer c.Close()
			io.Copy(c, c)
		}
	}()
	dialCtx, stop := context.WithTimeout(ctx, 5*time.Second)
	defer stop()
	c, err := clientNet.DialContextTCPAddrPort(dialCtx, netip.MustParseAddrPort("10.0.0.1:8443"))
	if err != nil {
		t.Fatal("application lost VPN with site allowlist:", err)
	}
	defer c.Close()
	c.SetDeadline(time.Now().Add(5 * time.Second))
	c.Write([]byte("application VPN"))
	b := make([]byte, 15)
	if _, err = io.ReadFull(c, b); err != nil || string(b) != "application VPN" {
		t.Fatalf("application echo %q: %v", b, err)
	}
	// Let the last ACK finish: an idle pooled browser socket sends no more
	// packets which could accidentally trigger the direct stack's RST.
	time.Sleep(250 * time.Millisecond)
	routed.resetTCP = func(flow) error { return os.ErrPermission }
	if changed := routed.updatePolicy(policyConfig{Whitelist: true}); changed != 1 {
		t.Fatalf("changed idle flows=%d", changed)
	}
	c.SetReadDeadline(time.Now().Add(250 * time.Millisecond))
	if _, err := c.Read(b); err == nil {
		t.Fatal("old browser connection stayed open after mode change")
	} else if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
		t.Fatal("idle browser connection did not close when SetTcpEntry failed")
	}
}
