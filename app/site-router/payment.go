//go:build linux || android

package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/netip"
	"time"

	"gvisor.dev/gvisor/pkg/tcpip"
)

func (o *otaStack) setPaymentDNS(servers []string) {
	for _, raw := range servers {
		if address, err := netip.ParseAddr(raw); err == nil && address.Is4() {
			o.paymentDNS = append(o.paymentDNS, tcpip.AddrFrom4(address.As4()))
		}
	}
}

// The excluded Android UID cannot bind to its own VPN. Resolve and validate the
// browser's destination through the existing encrypted WG device instead.
// This exposes one read-only fixed-host check, never an arbitrary HTTP proxy.
func (o *otaStack) probePaymentSite(parent context.Context) bool {
	ctx, cancel := context.WithTimeout(parent, 4*time.Second)
	defer cancel()
	resolver := &net.Resolver{PreferGo: true, Dial: func(ctx context.Context, _, _ string) (net.Conn, error) {
		servers := o.paymentDNS
		if len(servers) == 0 {
			servers = []tcpip.Address{tcpip.AddrFrom4([4]byte{1, 1, 1, 1})}
		}
		for _, address := range servers {
			attempt, cancel := context.WithTimeout(ctx, time.Second)
			connection, err := o.dialRemote(attempt, address, 53)
			cancel()
			if err == nil {
				return connection, nil
			}
		}
		return nil, errors.New("payment DNS unavailable")
	}}
	transport := &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, address string) (net.Conn, error) {
		if address != "yoomoney.ru:443" {
			return nil, errors.New("payment target rejected")
		}
		addresses, err := resolver.LookupNetIP(ctx, "ip4", "yoomoney.ru")
		if err != nil {
			return nil, err
		}
		for _, address := range addresses {
			connection, err := o.dialRemote(ctx, tcpip.AddrFrom4(address.As4()), 443)
			if err == nil {
				return connection, nil
			}
		}
		return nil, errors.New("payment HTTPS unavailable")
	}}
	defer transport.CloseIdleConnections()
	return checkPaymentHTTPS(ctx, transport, "https://yoomoney.ru/")
}

func checkPaymentHTTPS(ctx context.Context, transport http.RoundTripper, site string) bool {
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodHead, site, nil)
	if err != nil || request.URL.Scheme != "https" {
		return false
	}
	request.Header.Set("Cache-Control", "no-cache")
	response, err := client.Do(request)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.TLS != nil && response.StatusCode >= 200 && response.StatusCode < 400
}
