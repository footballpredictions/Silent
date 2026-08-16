package main

import (
	"fmt"
	"net"
	"strings"
	"time"
)

func deniedError(reason string) error {
	switch strings.TrimSpace(reason) {
	case "wrong_password":
		return fmt.Errorf("FATAL_AUTH: неверный пароль подключения")
	case "expired", "no_subscription":
		return fmt.Errorf("FATAL_AUTH: срок действия пароля истёк")
	case "device_mismatch":
		return fmt.Errorf("FATAL_AUTH: пароль привязан к другому устройству")
	default:
		return fmt.Errorf("FATAL_AUTH: доступ запрещён (%s)", reason)
	}
}

func parseConfigReply(resp string) (string, error) {
	if resp == "NOCONF" {
		return "", nil
	}
	if strings.HasPrefix(resp, "DENIED:") {
		return "", deniedError(strings.TrimPrefix(resp, "DENIED:"))
	}
	if strings.Contains(resp, "Silent-Access: 0") || strings.Contains(resp, "Silent-Vpn-Allowed: 0") {
		return "", deniedError("no_subscription")
	}
	return resp, nil
}

// ClassifyControlPayload: keepalive / GETCONF reply vs opaque WG packet.
// kind: keepalive | noconn | denied | config | data
func ClassifyControlPayload(b []byte) (kind string, err error) {
	if len(b) == 1 && b[0] == keepaliveByte {
		return "keepalive", nil
	}
	if len(b) == 0 {
		return "data", nil
	}
	switch b[0] {
	case 'D', 'N', '[', '#':
	default:
		return "data", nil
	}
	resp := string(b)
	if resp == "NOCONF" {
		return "noconn", nil
	}
	if strings.HasPrefix(resp, "DENIED:") {
		return "denied", deniedError(strings.TrimPrefix(resp, "DENIED:"))
	}
	if strings.Contains(resp, "Silent-Access: 0") || strings.Contains(resp, "Silent-Vpn-Allowed: 0") {
		return "denied", deniedError("no_subscription")
	}
	trim := strings.TrimSpace(resp)
	if strings.HasPrefix(trim, "[Interface]") {
		return "config", nil
	}
	return "data", nil
}

func getconfPayload(localPort, deviceID, password string) []byte {
	return []byte(fmt.Sprintf("GETCONF:%s|%s|%s", localPort, deviceID, password))
}

// RequestConfig запрашивает WireGuard конфиг через DTLS-соединение.
func RequestConfig(conn net.Conn, localPort, deviceID, password string) (string, error) {
	if _, err := conn.Write(getconfPayload(localPort, deviceID, password)); err != nil {
		return "", fmt.Errorf("отправка GETCONF: %w", err)
	}

	b := make([]byte, 4096)
	if err := conn.SetReadDeadline(time.Now().Add(15 * time.Second)); err != nil {
		return "", fmt.Errorf("установка дедлайна: %w", err)
	}
	n, err := conn.Read(b)
	_ = conn.SetReadDeadline(time.Time{})
	if err != nil {
		return "", fmt.Errorf("чтение ответа конфига: %w", err)
	}

	return parseConfigReply(string(b[:n]))
}
