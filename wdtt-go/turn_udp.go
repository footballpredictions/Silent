package main

import (
	"context"
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"

	"github.com/pion/stun/v3"
)

type udpEndpoint struct{ Host, Port string }

// Preserve the tested UDP URI selection; stream transports are deliberately absent.
func parseUDPEndpoint(raw string) (udpEndpoint, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" || strings.ContainsAny(raw, "@# \t\r\n") {
		return udpEndpoint{}, fmt.Errorf("invalid TURN endpoint")
	}
	if !strings.HasPrefix(raw, "turn:") && !strings.HasPrefix(raw, "turns:") {
		raw = "turn:" + raw
	}
	uri, err := stun.ParseURI(raw)
	if err != nil || uri.Scheme != stun.SchemeTypeTURN || uri.Proto != stun.ProtoTypeUDP {
		return udpEndpoint{}, fmt.Errorf("UDP TURN endpoint required")
	}
	if uri.Host == "" || uri.Port < 1 || uri.Port > 65535 {
		return udpEndpoint{}, fmt.Errorf("invalid TURN address")
	}
	return udpEndpoint{Host: uri.Host, Port: strconv.Itoa(uri.Port)}, nil
}

func validatedTURNURL(raw string) (string, error) {
	if _, err := parseUDPEndpoint(raw); err != nil {
		return "", err
	}
	return strings.TrimSpace(raw), nil
}

func selectUDPEndpoint(urls []string, sessionID int, hostOverride, portOverride string) (udpEndpoint, error) {
	var options []udpEndpoint
	for _, raw := range urls {
		endpoint, err := parseUDPEndpoint(raw)
		if err != nil {
			continue
		}
		if hostOverride != "" {
			endpoint.Host = hostOverride
		}
		if portOverride != "" {
			port, err := strconv.Atoi(portOverride)
			if err != nil || port < 1 || port > 65535 {
				return udpEndpoint{}, fmt.Errorf("invalid TURN port override")
			}
			endpoint.Port = portOverride
		}
		options = append(options, endpoint)
	}
	if len(options) == 0 {
		return udpEndpoint{}, fmt.Errorf("провайдер не выдал UDP-адрес TURN")
	}
	if sessionID < 0 {
		sessionID = 0
	}
	return options[sessionID%len(options)], nil
}

func dialUDPTURN(ctx context.Context, urls []string, sessionID int, params *TurnParams) (net.PacketConn, udpEndpoint, error) {
	if err := ctx.Err(); err != nil {
		return nil, udpEndpoint{}, err
	}
	endpoint, err := selectUDPEndpoint(urls, sessionID, params.Host, params.Port)
	if err != nil {
		return nil, endpoint, err
	}
	remote, err := resolveTurnUDPAddr(ctx, endpoint.Host, endpoint.Port)
	if err != nil {
		return nil, endpoint, fmt.Errorf("TURN UDP resolve: %w", err)
	}
	if err := ctx.Err(); err != nil {
		return nil, endpoint, err
	}
	conn, err := dialTurnUDP(remote)
	if err != nil {
		return nil, endpoint, fmt.Errorf("TURN UDP connect: %w", err)
	}
	_ = conn.SetReadBuffer(socketBufSize)
	_ = conn.SetWriteBuffer(socketBufSize)
	return &connectedUDPConn{conn}, endpoint, nil
}

// TURN DNS must use the existing LAN-bound resolver, never the active VPN DNS.
func resolveTurnUDPAddr(ctx context.Context, host, port string) (*net.UDPAddr, error) {
	if ip := net.ParseIP(host); ip != nil {
		number, err := strconv.Atoi(port)
		return &net.UDPAddr{IP: ip, Port: number}, err
	}
	lookup, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	addresses, err := vkDirectResolver().LookupIPAddr(lookup, host)
	if err != nil {
		return nil, err
	}
	for _, address := range addresses {
		if address.IP.To4() != nil {
			number, err := strconv.Atoi(port)
			return &net.UDPAddr{IP: address.IP, Port: number}, err
		}
	}
	return nil, fmt.Errorf("TURN UDP has no physical IPv4 address")
}
