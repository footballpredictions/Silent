package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const panelProxy = "silent-vpn-panel"

func panelHost(c Config) string      { return c.LANIP + ".silent.vpn" }
func panelURL(c Config) string       { return "http://" + panelHost(c) }
func legacyPanelURL(c Config) string { return fmt.Sprintf("http://%s:%d", c.LANIP, c.Port) }

// Only NDM's local proxy may assert a client address. A LAN browser cannot gain
// proxy trust by submitting X-Real-IP itself. The legacy IP:port keeps Basic auth.
func panelRequest(c Config, r *http.Request) (proxied bool, allowed bool) {
	host := strings.ToLower(r.Host)
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	host = strings.TrimSuffix(host, ".")
	remote, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return false, false
	}
	_, subnet, err := net.ParseCIDR(c.LANPrefix)
	if err != nil {
		return false, false
	}
	if host == c.LANIP {
		return false, subnet.Contains(net.ParseIP(remote))
	}
	if host != panelHost(c) || remote != c.LANIP {
		return false, false
	}
	values := r.Header.Values("X-Real-IP")
	if len(values) != 1 {
		return false, false
	}
	client := net.ParseIP(strings.TrimSpace(values[0]))
	return true, client != nil && client.To4() != nil && subnet.Contains(client) && !client.Equal(net.ParseIP(c.LANIP))
}

func panelOrigin(c Config, r *http.Request, proxied bool) bool {
	origin := r.Header.Get("Origin")
	if origin == "" {
		return true
	}
	if proxied {
		if origin == panelURL(c) {
			return true
		}
		// Older NDM versions rewrite Origin. Accept that form only with the
		// browser's same-origin assertion; cross-site and old ambiguous clients fail closed.
		return origin == legacyPanelURL(c) && r.Header.Get("Sec-Fetch-Site") == "same-origin"
	}
	return origin == legacyPanelURL(c)
}

type panelBinding struct {
	Schema int    `json:"schema"`
	Host   string `json:"host"`
	IP     string `json:"ip"`
	Port   int    `json:"port"`
	OwnDNS bool   `json:"own_dns"`
}

func (a *Agent) ndm(ctx context.Context, command string) ([]byte, error) {
	if a.ndmCommand != nil {
		return a.ndmCommand(ctx, command)
	}
	// Configuration output can contain router secrets: never include it in errors/logs.
	return exec.CommandContext(ctx, "ndmc", "-c", command).CombinedOutput()
}
func (a *Agent) ndmChange(ctx context.Context, command string) error {
	data, err := a.ndm(ctx, command)
	lower := strings.ToLower(string(data))
	for _, token := range []string{"error", "not found", "failed", "unknown command", "invalid", "unsupported"} {
		if strings.Contains(lower, token) {
			err = errors.New("NDM rejected command")
			break
		}
	}
	if err != nil {
		return fmt.Errorf("Keenetic: не удалось настроить локальную панель (%s)", command)
	}
	return nil
}

func proxySettings(c Config) []string {
	return []string{"domain static " + panelHost(c), "upstream http " + c.LANIP + fmt.Sprintf(" %d", c.Port), "preserve-host", "x-real-ip", "security-level private"}
}

// Inspect only our named resources, never save a copy of the router's full config.
func inspectPanel(data []byte, c Config) (proxy []string, dns []string, err error) {
	inProxy := false
	for _, raw := range strings.Split(string(data), "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "!") {
			continue
		}
		if raw[0] != ' ' && raw[0] != '\t' {
			inProxy = false
			if line == "ip http proxy "+panelProxy || line == "ip http proxy \""+panelProxy+"\"" {
				inProxy = true
				proxy = []string{}
				continue
			}
			fields := strings.Fields(line)
			if len(fields) >= 3 && fields[0] == "ip" && fields[1] == "host" && strings.Trim(fields[2], "\"") == panelHost(c) {
				if len(fields) != 4 || net.ParseIP(fields[3]) == nil {
					return nil, nil, errors.New("неожиданный формат DNS-записи панели")
				}
				dns = append(dns, fields[3])
			}
			if len(fields) == 4 && fields[0] == "ip" && fields[1] == "http" && fields[2] == "port" && fields[3] != "80" {
				return nil, nil, errors.New("для адреса панели без порта нужен штатный HTTP-порт Keenetic 80; порт роутера автоматически не меняется")
			}
		} else if inProxy {
			proxy = append(proxy, line)
		}
	}
	return
}

func (a *Agent) bindingPath() string {
	return filepath.Join(filepath.Dir(a.path), "panel-binding.json")
}
func (a *Agent) readBinding() (*panelBinding, error) {
	data, err := os.ReadFile(a.bindingPath())
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var saved panelBinding
	if json.Unmarshal(data, &saved) != nil || saved.Schema != 1 || saved.Host != panelHost(a.cfg) || saved.IP != a.cfg.LANIP || saved.Port != a.cfg.Port {
		return nil, errors.New("конфигурация локальной панели изменилась; восстановите прежнюю конфигурацию перед удалением")
	}
	return &saved, nil
}
func ownedProxy(proxy []string, c Config) bool {
	allowed := append(proxySettings(c), "preserve-origin")
	for _, line := range proxy {
		fields := strings.Fields(line)
		for i := range fields {
			fields[i] = strings.Trim(fields[i], "\"")
		}
		line = strings.Join(fields, " ")
		found := false
		for _, expected := range allowed {
			if line == expected {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func panelConfigured(proxy []string, records []string, c Config) bool {
	if proxy == nil || len(records) != 1 || records[0] != c.LANIP || !ownedProxy(proxy, c) {
		return false
	}
	for _, required := range proxySettings(c) {
		if required == "security-level private" {
			continue
		} // Native default; may be omitted from running-config.
		found := false
		for _, line := range proxy {
			fields := strings.Fields(line)
			for i := range fields {
				fields[i] = strings.Trim(fields[i], "\"")
			}
			if strings.Join(fields, " ") == required {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func (a *Agent) ensurePanel(ctx context.Context) (err error) {
	saved, err := a.readBinding()
	if err != nil {
		return err
	}
	data, err := a.ndm(ctx, "show running-config")
	if err != nil {
		return errors.New("нет доступа к ndmc; требуется штатный HTTP proxy KeeneticOS")
	}
	proxy, records, err := inspectPanel(data, a.cfg)
	if err != nil {
		return err
	}
	if proxy != nil && (saved == nil || !ownedProxy(proxy, a.cfg)) {
		return errors.New("имя HTTP proxy silent-vpn-panel занято; чужая конфигурация не изменена")
	}
	for _, address := range records {
		if address != a.cfg.LANIP {
			return errors.New("DNS-имя панели уже занято другим адресом")
		}
	}
	if saved == nil {
		saved = &panelBinding{Schema: 1, Host: panelHost(a.cfg), IP: a.cfg.LANIP, Port: a.cfg.Port, OwnDNS: len(records) == 0}
	}
	encoded, _ := json.Marshal(saved)
	if err = os.WriteFile(a.bindingPath()+".new", encoded, 0600); err != nil {
		return err
	}
	if err = os.Rename(a.bindingPath()+".new", a.bindingPath()); err != nil {
		return err
	}
	defer func() {
		if err != nil {
			cleanup, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			err = errors.Join(err, a.cleanupPanel(cleanup))
		}
	}()
	changed := false
	if len(records) == 0 {
		if err = a.ndmChange(ctx, "ip host "+panelHost(a.cfg)+" "+a.cfg.LANIP); err != nil {
			return err
		}
		changed = true
	}
	for _, setting := range proxySettings(a.cfg) {
		found := false
		for _, existing := range proxy {
			if existing == setting {
				found = true
				break
			}
		}
		if !found {
			if err = a.ndmChange(ctx, "ip http proxy "+panelProxy+" "+setting); err != nil {
				return err
			}
			changed = true
		}
	}
	// Available since 4.2; older NDM uses the strict same-origin fallback above.
	hasOrigin := false
	for _, line := range proxy {
		if line == "preserve-origin" {
			hasOrigin = true
		}
	}
	if !hasOrigin && a.ndmChange(ctx, "ip http proxy "+panelProxy+" preserve-origin") == nil {
		changed = true
	}
	data, err = a.ndm(ctx, "show running-config")
	if err != nil {
		return errors.New("не удалось проверить настройку адреса панели")
	}
	verifiedProxy, verifiedRecords, checkErr := inspectPanel(data, a.cfg)
	if checkErr != nil || !panelConfigured(verifiedProxy, verifiedRecords, a.cfg) {
		return errors.New("NDM не подтвердил DNS и private HTTP proxy панели")
	}
	if changed {
		return a.ndmChange(ctx, "system configuration save")
	}
	return nil
}

func (a *Agent) cleanupPanel(ctx context.Context) error {
	saved, err := a.readBinding()
	if err != nil || saved == nil {
		return err
	}
	data, err := a.ndm(ctx, "show running-config")
	if err != nil {
		return errors.New("не удалось проверить собственную конфигурацию панели")
	}
	proxy, records, err := inspectPanel(data, a.cfg)
	if err != nil {
		return err
	}
	if proxy != nil && !ownedProxy(proxy, a.cfg) {
		return errors.New("HTTP proxy панели изменён вручную; чужие настройки сохранены")
	}
	for _, address := range records {
		if address != saved.IP {
			return errors.New("DNS панели изменён вручную; чужая запись сохранена")
		}
	}
	if proxy != nil {
		if err = a.ndmChange(ctx, "no ip http proxy "+panelProxy); err != nil {
			return err
		}
	}
	if saved.OwnDNS && len(records) > 0 {
		if err = a.ndmChange(ctx, "no ip host "+saved.Host+" "+saved.IP); err != nil {
			return err
		}
	}
	if err = a.ndmChange(ctx, "system configuration save"); err != nil {
		return err
	}
	return os.Remove(a.bindingPath())
}
