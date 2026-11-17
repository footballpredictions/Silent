//go:build linux || android

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"

	"golang.org/x/crypto/curve25519"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

func TestPaymentExitRetargetKeepsWireGuardDeviceAndTun(t *testing.T) {
	private := make([]byte, 32)
	rand.Read(private)
	public, _ := curve25519.X25519(private, curve25519.Basepoint)
	localTun, local, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	wg := device.NewDevice(localTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "payment-test: "))
	defer wg.Close()
	exit := func(name string) string {
		exitTun, stack, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.1")}, nil, 1200)
		if err != nil {
			t.Fatal(err)
		}
		peer := device.NewDevice(exitTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "payment-exit: "))
		t.Cleanup(peer.Close)
		key := make([]byte, 32)
		rand.Read(key)
		pub, _ := curve25519.X25519(key, curve25519.Basepoint)
		err = peer.IpcSet(fmt.Sprintf("private_key=%s\nlisten_port=0\npublic_key=%s\nallowed_ip=10.66.66.2/32\n", hex.EncodeToString(key), hex.EncodeToString(public)))
		if err != nil {
			t.Fatal(err)
		}
		if err = peer.Up(); err != nil {
			t.Fatal(err)
		}
		state, _ := peer.IpcGet()
		port := ""
		for _, line := range strings.Split(state, "\n") {
			if strings.HasPrefix(line, "listen_port=") {
				port = strings.TrimPrefix(line, "listen_port=")
			}
		}
		listener, err := stack.ListenTCPAddrPort(netip.MustParseAddrPort("10.66.66.1:8000"))
		if err != nil {
			t.Fatal(err)
		}
		server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, name) })}
		go server.Serve(listener)
		t.Cleanup(func() { server.Close() })
		return fmt.Sprintf("private_key=%s\npublic_key=%s\nendpoint=127.0.0.1:%s\nallowed_ip=0.0.0.0/0\n", hex.EncodeToString(private), hex.EncodeToString(pub), port)
	}
	first, second := exit("first"), exit("second")
	if err = wg.IpcSet(first); err != nil {
		t.Fatal(err)
	}
	if err = wg.Up(); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Timeout: 4 * time.Second, Transport: &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return local.DialContextTCP(ctx, &net.TCPAddr{IP: net.ParseIP("10.66.66.1"), Port: 8000})
	}}}
	read := func(want string) {
		resp, err := client.Get("http://10.66.66.1:8000/api/payments/preview")
		if err != nil {
			t.Fatal(err)
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if string(body) != want {
			t.Fatalf("exit=%q want=%q", body, want)
		}
	}
	read("first")
	input, _ := json.Marshal(map[string]any{"revision": 1, "wireguard": second})
	var output bytes.Buffer
	err = applyRouterUpdates(strings.NewReader(string(input)+"\n"), newPolicy(false, nil, nil), &output, nil, nil, func(config string) error { return wg.IpcSet("replace_peers=true\n" + config) })
	if err != nil || output.String() != "POLICY_READY:1\n" {
		t.Fatalf("update not acknowledged: %v %s", err, output.String())
	}
	read("second") // No Close/Up/new TUN, actual encrypted TCP reaches the replacement peer.
	state, _ := wg.IpcGet()
	if strings.Count(state, "public_key=") != 1 {
		t.Fatal("previous exit peer retained")
	}
}

func TestPaymentControlRejectsUnappliedConfig(t *testing.T) {
	var out bytes.Buffer
	applyRouterUpdates(strings.NewReader("{\"revision\":5,\"wireguard\":\"invalid\"}\n"), newPolicy(false, nil, nil), &out, nil, nil, func(string) error { return fmt.Errorf("invalid") })
	if out.String() != "WG_FAILED:5\n" {
		t.Fatal("failed config was acknowledged as ready")
	}
}

func TestPaymentHTTPSUsesVerifiedTLSAndNoRedirectOrPaymentWrite(t *testing.T) {
	status := 200
	methods := make(chan string, 8)
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		methods <- r.Method
		w.Header().Set("Location", "https://untrusted.invalid/")
		w.WriteHeader(status)
	}))
	defer server.Close()
	transport := server.Client().Transport
	if !checkPaymentHTTPS(context.Background(), transport, server.URL) {
		t.Fatal("trusted TLS rejected")
	}
	if <-methods != "HEAD" {
		t.Fatal("probe must be read-only HEAD")
	}
	status = 302
	if !checkPaymentHTTPS(context.Background(), transport, server.URL) {
		t.Fatal("redirect should not be followed")
	}
	<-methods
	status = 503
	if checkPaymentHTTPS(context.Background(), transport, server.URL) {
		t.Fatal("HTTP failure accepted")
	}
	<-methods
	if checkPaymentHTTPS(context.Background(), http.DefaultTransport, server.URL) {
		t.Fatal("invalid certificate accepted")
	}
	if checkPaymentHTTPS(context.Background(), transport, "http://yoomoney.ru/") {
		t.Fatal("plaintext accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if checkPaymentHTTPS(ctx, transport, server.URL) {
		t.Fatal("cancelled probe accepted")
	}
}
