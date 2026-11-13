package main

import (
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net/netip"
	"strings"
)

// relayWireGuardConfig is the identity issued by WDTT GETCONF, not the API's
// device registration keys. The server installs this peer on its interface.
type relayWireGuardConfig struct {
	address string
	uapi    string
}

func parseRelayWireGuardConfig(raw, localPort string) (relayWireGuardConfig, error) {
	var address, privateKey, publicKey string
	var section string
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "[") {
			section = line
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		value = strings.TrimSpace(value)
		switch section + strings.TrimSpace(key) {
		case "[Interface]Address":
			address = value
		case "[Interface]PrivateKey":
			privateKey = value
		case "[Peer]PublicKey":
			publicKey = value
		}
	}
	prefix, err := netip.ParsePrefix(address)
	if err != nil || !prefix.Addr().Is4() || prefix.Bits() != 32 || !prefix.Addr().IsGlobalUnicast() {
		return relayWireGuardConfig{}, errors.New("WDTT не выдал адрес WireGuard")
	}
	privateHex, err := wireGuardKeyHex(privateKey)
	if err != nil {
		return relayWireGuardConfig{}, errors.New("WDTT выдал неверный ключ клиента")
	}
	publicHex, err := wireGuardKeyHex(publicKey)
	if err != nil {
		return relayWireGuardConfig{}, errors.New("WDTT выдал неверный ключ сервера")
	}
	return relayWireGuardConfig{
		address: prefix.String(),
		uapi:    fmt.Sprintf("private_key=%s\nlisten_port=0\nreplace_peers=true\npublic_key=%s\nendpoint=127.0.0.1:%s\nallowed_ip=0.0.0.0/0\npersistent_keepalive_interval=25\n", privateHex, publicHex, localPort),
	}, nil
}

func wireGuardKeyHex(key string) (string, error) {
	raw, err := base64.RawStdEncoding.DecodeString(strings.TrimRight(key, "="))
	if err != nil || len(raw) != 32 {
		return "", errors.New("invalid WireGuard key")
	}
	return hex.EncodeToString(raw), nil
}
