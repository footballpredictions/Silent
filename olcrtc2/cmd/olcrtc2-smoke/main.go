// Command olcrtc2-smoke: Phase 1 localhost SOCKS over mock carrier.
//
//	go run ./cmd/olcrtc2-smoke
package main

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"time"

	"github.com/footballpredictions/Silent/olcrtc2/edge"
)

const keyHex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func main() {
	want := "ok-olcrtc2-smoke"
	httpLn, err := net.Listen("tcp", "127.0.0.1:0")
	must(err)
	defer httpLn.Close()
	go func() {
		_ = http.Serve(httpLn, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.WriteString(w, want)
		}))
	}()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	pair, err := edge.StartLoopback(ctx, keyHex, "127.0.0.1:0")
	must(err)
	defer pair.Close()

	proxyURL, err := url.Parse("socks5://" + pair.SocksAddr)
	must(err)
	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			Proxy: http.ProxyURL(proxyURL),
		},
	}
	resp, err := client.Get("http://" + httpLn.Addr().String() + "/")
	must(err)
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	must(err)
	if string(body) != want {
		fmt.Fprintf(os.Stderr, "FAIL body=%q\n", body)
		os.Exit(1)
	}
	fmt.Printf("PASS olcrtc2 phase1 socks=%s http=%s\n", pair.SocksAddr, httpLn.Addr())
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
