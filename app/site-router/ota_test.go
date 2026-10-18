//go:build linux || android

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/crypto/curve25519"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

type droppingBind struct {
	conn.Bind
	drop atomic.Bool
}

func (b *droppingBind) Send(packets [][]byte, endpoint conn.Endpoint) error {
	if b.drop.Load() {
		return nil
	}
	return b.Bind.Send(packets, endpoint)
}

func TestOTAOverExistingEncryptedWireGuardKeepsApplicationTCP(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	hostTun, host, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	defer hostTun.Close()
	exitTun, exit, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.1")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	adapter := &routedTun{file: writer, events: make(chan tun.Event, 1), policy: newPolicy(false, nil, nil),
		packets: make(chan []byte, 256), packetErrors: make(chan error, 1), mtu: 1200}
	api, err := newOTAStack(ctx, "10.66.66.2", 1200, func(packet []byte) error {
		select {
		case adapter.packets <- packet:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	defer api.stack.Close()
	adapter.ota = api
	// Android application packets and OTA packets enter the same actual routedTun.
	go func() {
		for {
			b := [][]byte{make([]byte, 65535)}
			sizes := make([]int, 1)
			if _, err := hostTun.Read(b, sizes, 0); err != nil {
				return
			}
			select {
			case adapter.packets <- b[0][:sizes[0]]:
			case <-ctx.Done():
				return
			}
		}
	}()
	go func() {
		r := bufio.NewReader(reader)
		for {
			header := make([]byte, 4)
			if _, err := io.ReadFull(r, header); err != nil {
				return
			}
			size := int(binary.BigEndian.Uint16(header[2:4]))
			if size < 20 {
				return
			}
			packet := make([]byte, size)
			copy(packet, header)
			if _, err := io.ReadFull(r, packet[4:]); err != nil {
				return
			}
			if _, err := hostTun.Write([][]byte{packet}, 0); err != nil {
				return
			}
		}
	}()
	link := &droppingBind{Bind: conn.NewDefaultBind()}
	clientWG := device.NewDevice(adapter, link, device.NewLogger(device.LogLevelError, "test-client: "))
	exitWG := device.NewDevice(exitTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "test-exit: "))
	defer exitWG.Close()
	defer func() { adapter.packetErrors <- io.EOF; clientWG.Close() }()
	privateA := make([]byte, 32)
	privateB := make([]byte, 32)
	rand.Read(privateA)
	rand.Read(privateB)
	publicA, _ := curve25519.X25519(privateA, curve25519.Basepoint)
	publicB, _ := curve25519.X25519(privateB, curve25519.Basepoint)
	if err := exitWG.IpcSet(fmt.Sprintf("private_key=%s\nlisten_port=0\npublic_key=%s\nallowed_ip=10.66.66.2/32\n", hex.EncodeToString(privateB), hex.EncodeToString(publicA))); err != nil {
		t.Fatal(err)
	}
	if err := exitWG.Up(); err != nil {
		t.Fatal(err)
	}
	state, err := exitWG.IpcGet()
	if err != nil {
		t.Fatal(err)
	}
	port := ""
	for _, line := range strings.Split(state, "\n") {
		if strings.HasPrefix(line, "listen_port=") {
			port = strings.TrimPrefix(line, "listen_port=")
		}
	}
	if port == "" || port == "0" {
		t.Fatalf("No exit UDP port: %q", port)
	}
	if err := clientWG.IpcSet(fmt.Sprintf("private_key=%s\npublic_key=%s\nendpoint=127.0.0.1:%s\nallowed_ip=0.0.0.0/0\n", hex.EncodeToString(privateA), hex.EncodeToString(publicB), port)); err != nil {
		t.Fatal(err)
	}
	if err := clientWG.Up(); err != nil {
		t.Fatal(err)
	}
	listener, err := exit.ListenTCPAddrPort(netip.MustParseAddrPort("10.66.66.1:8000"))
	if err != nil {
		t.Fatal(err)
	}
	payload := bytes.Repeat([]byte("apk-bytes-through-encrypted-wg"), 200_000)
	applicationConnections := make(chan string, 4)
	exitHTTP := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/updates/check":
			io.WriteString(w, `{"available":true,"version":"1.0.999"}`)
		case "/api/vpn/routing-policy":
			io.WriteString(w, `{"schema_version":1,"revision":"policy-through-existing-wg"}`)
		case "/api/users/me", "/api/users/devices/fixture-device", "/api/auth/refresh":
			if r.Header.Get("Authorization") != "Bearer fixture" {
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			io.WriteString(w, `{"devices":[{"id":"other","is_connected":true}]}`)
		case "/api/updates/download/android":
			w.Write(payload)
		case "/ordinary":
			applicationConnections <- r.RemoteAddr
			io.WriteString(w, "application VPN still works")
		default:
			http.NotFound(w, r)
		}
	})}
	go exitHTTP.Serve(listener)
	defer exitHTTP.Close()
	proxy, err := api.serve(0)
	if err != nil {
		t.Fatal(err)
	}
	// serve(0) returns server but not listener address: use handler with httptest instead.
	proxy.Close()
	transport := &http.Transport{DialContext: api.dial, DisableCompression: true}
	defer transport.CloseIdleConnections()
	local := httptest.NewServer(otaHandler(transport))
	defer local.Close()
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Get(local.URL + "/api/updates/check?platform=android&version=1.0.1")
	if err != nil {
		t.Fatal(err)
	}
	metadata, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil || resp.StatusCode != 200 || !bytes.Contains(metadata, []byte(`"available":true`)) {
		t.Fatalf("Metadata: %d %s %v", resp.StatusCode, metadata, err)
	}
	if adapter.pathSent.Load() != 0 {
		t.Fatal("Internal API probes must not create application-traffic demand")
	}
	appClient := &http.Client{Timeout: 20 * time.Second, Transport: &http.Transport{DialContext: func(ctx context.Context, _, addr string) (net.Conn, error) {
		return host.DialContextTCP(ctx, &net.TCPAddr{IP: net.ParseIP("10.66.66.1"), Port: 8000})
	}}}
	defer appClient.CloseIdleConnections()
	done := make(chan error, 1)
	go func() {
		r, e := appClient.Get("http://10.66.66.1:8000/ordinary")
		if e != nil {
			done <- e
			return
		}
		b, e := io.ReadAll(r.Body)
		r.Body.Close()
		if e == nil && string(b) != "application VPN still works" {
			e = fmt.Errorf("app traffic changed: %q", b)
		}
		done <- e
	}()
	resp, err = client.Get(local.URL + "/api/updates/download/android")
	if err != nil {
		t.Fatal(err)
	}
	apk, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil || !bytes.Equal(apk, payload) {
		t.Fatalf("APK stream corrupt: %d/%d %v", len(apk), len(payload), err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	firstConnection := <-applicationConnections
	resp, err = client.Get(local.URL + "/api/vpn/routing-policy")
	if err != nil {
		t.Fatal(err)
	}
	routingPolicy, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil || resp.StatusCode != 200 || !bytes.Contains(routingPolicy, []byte("policy-through-existing-wg")) || resp.Header.Get("X-Silent-Upstream") != "1" {
		t.Fatalf("Routing policy did not use existing encrypted WG: %d %s %v", resp.StatusCode, routingPolicy, err)
	}
	for _, tc := range []struct{ method, path string }{
		{"GET", "/api/users/me"}, {"PATCH", "/api/users/devices/fixture-device"},
		{"DELETE", "/api/users/devices/fixture-device"}, {"POST", "/api/auth/refresh"},
	} {
		request, _ := http.NewRequest(tc.method, local.URL+tc.path, strings.NewReader(`{"fixture":true}`))
		request.Header.Set("Authorization", "Bearer fixture")
		response, err := client.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 || response.Header.Get("X-Silent-Upstream") != "1" || !bytes.Contains(body, []byte(`"other"`)) {
			t.Fatalf("Session %s failed over existing encrypted WG: %s %v", tc.method, body, err)
		}
	}
	var acknowledgement bytes.Buffer
	if err := applyTargetUpdates(strings.NewReader("{\"revision\":1,\"targets\":[\"203.0.113.7\"]}\n"), adapter.policy, &acknowledgement); err != nil {
		t.Fatal(err)
	}
	if acknowledgement.String() != "POLICY_READY:1\n" {
		t.Fatal("Target update was not acknowledged")
	}
	ordinary, err := appClient.Get("http://10.66.66.1:8000/ordinary")
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, ordinary.Body)
	ordinary.Body.Close()
	if <-applicationConnections != firstConnection {
		t.Fatal("A target refresh replaced the existing application TCP connection")
	}
	if adapter.pathSent.Load() == 0 || adapter.pathReceived.Load() == 0 {
		t.Fatal("Application packets did not reach the real VPN path counters")
	}
	if resp.Header.Get("X-Silent-Upstream") != "1" {
		t.Fatal("An actual encrypted upstream response was not marked")
	}
	if resp, err := client.Post(local.URL+"/api/updates/download/android", "text/plain", nil); err != nil {
		t.Fatal(err)
	} else {
		resp.Body.Close()
		if resp.StatusCode != 403 {
			t.Fatal("Proxy allowed writes")
		}
	}
	if resp, err := client.Get(local.URL + "/api/admin/users"); err != nil {
		t.Fatal(err)
	} else {
		resp.Body.Close()
		if resp.StatusCode != 403 {
			t.Fatal("Proxy allowed unrelated API")
		}
	}
	// A carrier black hole can retain Network, IP, WG, and the native process.
	// The real encrypted device must expose sent packets without replies.
	time.Sleep(100 * time.Millisecond)
	beforeSent, beforeReceived := adapter.pathSent.Load(), adapter.pathReceived.Load()
	link.drop.Store(true)
	blocked := &http.Client{Timeout: 400 * time.Millisecond, Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return host.DialContextTCP(ctx, &net.TCPAddr{IP: net.ParseIP("10.66.66.1"), Port: 8000})
	}}}
	if response, err := blocked.Get("http://10.66.66.1:8000/ordinary"); err == nil {
		response.Body.Close()
		t.Fatal("Black-holed tunnel unexpectedly passed application traffic")
	}
	blocked.CloseIdleConnections()
	if adapter.pathSent.Load() <= beforeSent || adapter.pathReceived.Load() != beforeReceived {
		t.Fatal("The unchanged live WG device did not expose the stalled data path")
	}
	link.drop.Store(false)
	response, err := client.Get(local.URL + "/api/updates/check?platform=android")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.Header.Get("X-Silent-Upstream") != "1" {
		t.Fatal("The original WG device did not recover")
	}
}
