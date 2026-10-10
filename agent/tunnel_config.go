package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

type wgConfig struct {
	IPC, Address, DNS string
	MTU               int
}

func parseWG(text string) (wgConfig, error) {
	c := wgConfig{MTU: 1280}
	peer := false
	private, public := false, false
	s := bufio.NewScanner(strings.NewReader(text))
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if line == "[Interface]" {
			peer = false
			continue
		}
		if line == "[Peer]" {
			if public {
				return c, errors.New("Несколько peers не поддерживаются")
			}
			peer = true
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			return c, errors.New("Некорректный WG-конфиг")
		}
		key, value := strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
		switch key {
		case "PrivateKey", "PublicKey", "PresharedKey":
			b, err := base64.StdEncoding.DecodeString(value)
			if err != nil || len(b) != 32 {
				return c, errors.New("Некорректный WG-ключ")
			}
			name := map[string]string{"PrivateKey": "private_key", "PublicKey": "public_key", "PresharedKey": "preshared_key"}[key]
			if key == "PrivateKey" {
				if peer || private {
					return c, errors.New("Некорректный PrivateKey")
				}
				private = true
			}
			if key == "PublicKey" {
				if !peer || public {
					return c, errors.New("Некорректный PublicKey")
				}
				public = true
			}
			c.IPC += name + "=" + hex.EncodeToString(b) + "\n"
		case "Address":
			if peer {
				return c, errors.New("Некорректный Address")
			}
			value = strings.Split(value, ",")[0]
			if !strings.Contains(value, "/") {
				value += "/32"
			}
			ip, _, err := net.ParseCIDR(strings.TrimSpace(value))
			if err != nil || ip.To4() == nil {
				return c, errors.New("Нужен IPv4 WG адрес")
			}
			c.Address = strings.TrimSpace(value)
		case "DNS":
			c.DNS = value
		case "MTU":
			n, err := strconv.Atoi(value)
			if err != nil || n < 576 || n > 1420 {
				return c, errors.New("Некорректный MTU")
			}
			c.MTU = n
		case "Endpoint":
			if !peer {
				return c, errors.New("Некорректный Endpoint")
			}
			c.IPC += "endpoint=127.0.0.1:9000\n"
		case "AllowedIPs", "PersistentKeepalive", "ListenPort": // fixed locally; never trust route directives from a file.
		default:
			return c, fmt.Errorf("Неподдерживаемое поле WG: %s", key)
		}
	}
	if s.Err() != nil || !private || !public || c.Address == "" {
		return c, errors.New("Неполный WG-конфиг")
	}
	c.IPC += "replace_allowed_ips=true\nallowed_ip=0.0.0.0/0\npersistent_keepalive_interval=25\nendpoint=127.0.0.1:9000\n"
	return c, nil
}

func runCommand(ctx context.Context, name string, args ...string) error {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = append(os.Environ(), "PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin")
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("%s: %w: %.500s", filepath.Base(name), err, string(output))
	}
	return nil
}
func (a *Agent) network(ctx context.Context, op string, args ...string) error {
	c := a.cfg
	argv := []string{filepath.Join(a.root, "network.sh"), op, c.LANInterface, c.LANIP, c.LANPrefix, fmt.Sprint(c.Port)}
	argv = append(argv, args...)
	return a.run(ctx, "/bin/sh", argv...)
}

func handshakeReady(s string) bool {
	for _, line := range strings.Split(s, "\n") {
		if strings.HasPrefix(line, "last_handshake_time_sec=") {
			n, _ := strconv.ParseInt(strings.TrimPrefix(line, "last_handshake_time_sec="), 10, 64)
			if n > 0 {
				return true
			}
		}
	}
	return false
}
