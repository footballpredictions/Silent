package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
)

const version = "1.0.169"
const tunnelAPI = "http://10.66.66.1:8000"
const bootstrapHash = "T5oeMQkn6iF1XfUfhxGQ0h6j4lHEoJ5wTGEyi1Q_2cc"
const iface = "svkeen"

type Config struct {
	LANInterface  string `json:"lan_interface"`
	LANIP         string `json:"lan_ip"`
	LANPrefix     string `json:"lan_prefix"`
	Port          int    `json:"port"`
	AdminPassword string `json:"admin_password"`
	Fingerprint   string `json:"fingerprint"`
	Token         string `json:"access_token,omitempty"`
	RefreshToken  string `json:"refresh_token,omitempty"`
	Email         string `json:"email,omitempty"`
	DNSPreset     string `json:"dns_preset"`
	DNSCustom     string `json:"dns_custom,omitempty"`
	Direct        bool   `json:"ru_direct"`
	Reconnect     bool   `json:"reconnect"`
}

func randomID() string {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

func (c Config) validate() error {
	ip := net.ParseIP(c.LANIP)
	_, subnet, err := net.ParseCIDR(c.LANPrefix)
	if err != nil || ip == nil || ip.To4() == nil || !ip.IsPrivate() || !subnet.IP.IsPrivate() || !subnet.Contains(ip) {
		return errors.New("нужен частный IPv4 LAN и его подсеть")
	}
	if ones, _ := subnet.Mask.Size(); ones < 8 || ones > 30 {
		return errors.New("некорректная подсеть LAN")
	}
	if c.LANInterface == "" || len(c.LANInterface) > 15 || strings.ContainsAny(c.LANInterface, " \t\r\n/;'") {
		return errors.New("некорректный LAN-интерфейс")
	}
	if c.Port < 1024 || c.Port > 65535 || len(c.AdminPassword) < 16 {
		return errors.New("нужен порт 1024–65535 и пароль панели от 16 символов")
	}
	if c.DNSPreset != "server" && c.DNSPreset != "custom" {
		return errors.New("неизвестный режим DNS")
	}
	if c.DNSPreset == "custom" {
		_, err = dnsAddresses(c.DNSCustom)
		return err
	}
	return nil
}

func dnsAddresses(s string) ([]string, error) {
	var out []string
	for _, v := range strings.Split(s, ",") {
		v = strings.TrimSpace(v)
		ip := net.ParseIP(v)
		if ip == nil || ip.To4() == nil {
			return nil, errors.New("DNS: укажите IPv4 адреса через запятую")
		}
		out = append(out, v)
	}
	if len(out) < 1 || len(out) > 3 {
		return nil, errors.New("DNS: нужно от 1 до 3 адресов")
	}
	return out, nil
}

func loadConfig(path string) (Config, error) {
	var c Config
	b, err := os.ReadFile(path)
	if err != nil {
		return c, err
	}
	err = json.Unmarshal(b, &c)
	if err != nil {
		return c, err
	}
	return c, c.validate()
}
func saveConfig(path string, c Config) error {
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	if err = os.WriteFile(path+".new", b, 0600); err != nil {
		return err
	}
	return os.Rename(path+".new", path)
}
