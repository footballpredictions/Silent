package main

import (
	"context"
	"errors"
	"log"
	"net"
	"runtime"
	"slices"
	"sync"
	"time"

	http "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
	"golang.org/x/net/proxy"
)

var vkAuthDNSRecovered sync.Once

type vkDNSFallbackDialer struct {
	primary net.Dialer
	lookup  func(context.Context, string) ([]net.IP, error)
}

func (d vkDNSFallbackDialer) Dial(network, address string) (net.Conn, error) {
	return d.DialContext(context.Background(), network, address)
}

func (d vkDNSFallbackDialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	conn, primaryErr := d.primary.DialContext(ctx, network, address)
	var dnsErr *net.DNSError
	if ctx.Err() != nil || !errors.As(primaryErr, &dnsErr) || dnsErr.IsNotFound {
		return conn, primaryErr
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, primaryErr
	}
	ips, err := d.lookup(ctx, host)
	if err != nil {
		return nil, primaryErr
	}
	for _, ip := range ips {
		conn, err = d.primary.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if err == nil {
			vkAuthDNSRecovered.Do(func() {
				log.Print("[VPN] DNS для VK восстановлен через запасной резолвер")
			})
			return conn, nil
		}
	}
	if err != nil {
		return nil, err
	}
	return nil, primaryErr
}

func vkAuthDialOption() tlsclient.HttpClientOption {
	primary := newVkDirectDialer()
	if runtime.GOOS != "windows" {
		return tlsclient.WithDialer(primary)
	}
	return tlsclient.WithProxyDialerFactory(func(_ string, _ time.Duration, _ *net.TCPAddr, _ http.Header, _ tlsclient.Logger) (proxy.ContextDialer, error) {
		return vkDNSFallbackDialer{
			primary: primary,
			lookup: func(ctx context.Context, host string) ([]net.IP, error) {
				var localIP net.IP
				if addr, ok := primary.LocalAddr.(*net.TCPAddr); ok {
					localIP = addr.IP
				}
				return lookupVKAuthDNS(ctx, host, vkAdapterDNS(localIP))
			},
		}, nil
	})
}

// Probe complete DNS requests. A successful UDP dial alone says nothing about
// the resolver, so advance when a candidate does not return a usable answer.
func lookupVKAuthDNS(ctx context.Context, host string, adapterServers []string) ([]net.IP, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	servers := slices.Clone(adapterServers)
	for _, server := range vkPublicDNSServers {
		if !slices.Contains(servers, server) {
			servers = append(servers, server)
		}
	}
	var lastErr error
	for _, server := range servers {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		candidateCtx, candidateCancel := context.WithTimeout(ctx, 800*time.Millisecond)
		resolver := &net.Resolver{
			PreferGo: true,
			Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
				return dialViaLan(ctx, network, server, 800*time.Millisecond)
			},
		}
		ips, err := resolver.LookupIP(candidateCtx, "ip4", host)
		candidateCancel()
		if err == nil && len(ips) != 0 {
			return ips, nil
		}
		lastErr = err
	}
	return nil, lastErr
}
