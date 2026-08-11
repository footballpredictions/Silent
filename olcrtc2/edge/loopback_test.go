package edge

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/url"
	"testing"
	"time"
)

const testKeyHex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func TestLoopbackHTTPViaSOCKS(t *testing.T) {
	want := "ok-olcrtc2-phase1"
	httpLn, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer httpLn.Close()
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, want)
	})
	go func() { _ = http.Serve(httpLn, mux) }()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pair, err := StartLoopback(ctx, testKeyHex, "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer pair.Close()

	transport := &http.Transport{
		Proxy: http.ProxyURL(mustSOCKSURL(t, pair.SocksAddr)),
	}
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second}
	url := "http://" + httpLn.Addr().String() + "/"
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("GET via socks: %v", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	if string(body) != want {
		t.Fatalf("body=%q want=%q", body, want)
	}
}

func mustSOCKSURL(t *testing.T, addr string) *url.URL {
	t.Helper()
	u, err := url.Parse("socks5://" + addr)
	if err != nil {
		t.Fatal(err)
	}
	return u
}
