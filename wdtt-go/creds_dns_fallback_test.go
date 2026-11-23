package main

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"
)

func TestVKAuthDialRecoversWhenPrimaryDNSIsUnavailable(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	_, port, err := net.SplitHostPort(listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}

	const host = "vk-auth-fallback.test"
	var fallbackHost string
	dialer := vkDNSFallbackDialer{
		primary: net.Dialer{Resolver: &net.Resolver{
			PreferGo: true,
			Dial: func(context.Context, string, string) (net.Conn, error) {
				return nil, errors.New("DNS server unreachable")
			},
		}},
		lookup: func(_ context.Context, name string) ([]net.IP, error) {
			fallbackHost = name
			return []net.IP{net.IPv4(127, 0, 0, 1)}, nil
		},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, port))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if fallbackHost != host || conn.RemoteAddr().String() != listener.Addr().String() {
		t.Fatalf("unexpected lookup/connection: host=%q peer=%s", fallbackHost, conn.RemoteAddr())
	}
}

func TestVKAuthDialDoesNotUseDNSFallbackForConnectionRefusal(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	dialer := vkDNSFallbackDialer{
		lookup: func(context.Context, string) ([]net.IP, error) {
			t.Fatal("a TCP error must not trigger another DNS lookup")
			return nil, nil
		},
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	conn, err := dialer.DialContext(ctx, "tcp4", address)
	if err == nil {
		conn.Close()
		t.Fatal("unexpected TCP connection")
	}
}
