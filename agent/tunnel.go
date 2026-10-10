//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
)

func (a *Agent) interrupt() {
	a.mu.RLock()
	cancel := a.cancel
	a.mu.RUnlock()
	if cancel != nil {
		cancel()
	}
}
func (a *Agent) disconnect() error {
	// Remove redirection/policy first, then stop data path. Own chains only.
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	netErr := a.network(ctx, "down")
	a.stopDNS()
	if a.stopTunnel != nil {
		a.stopTunnel()
		a.stopTunnel = nil
	}
	a.mu.Lock()
	was := a.connected
	a.connected = false
	a.upstream = nil
	a.cfg.Reconnect = false
	a.mu.Unlock()
	persistErr := a.persist()
	if was {
		_, _ = a.call(ctx, "POST", "/api/vpn/disconnect", map[string]string{"device_fingerprint": a.cfg.Fingerprint})
	}
	return errors.Join(netErr, persistErr)
}

func (a *Agent) connect(parent context.Context) (err error) {
	a.op.Lock()
	defer a.op.Unlock()
	if a.isConnected() {
		return nil
	}
	ctx, cancel := context.WithTimeout(parent, 100*time.Second)
	a.mu.Lock()
	a.cancel = cancel
	a.mu.Unlock()
	defer func() {
		cancel()
		a.mu.Lock()
		a.cancel = nil
		a.mu.Unlock()
		if err != nil {
			a.disconnect()
		}
	}()
	if err = a.network(ctx, "check"); err != nil {
		return err
	}
	if err = a.network(ctx, "down"); err != nil {
		return err
	}
	_, err = a.call(ctx, "GET", "/api/users/me", nil)
	if err != nil {
		var ae *apiError
		if errors.As(err, &ae) && ae.Code == 401 {
			a.refresh(ctx)
		} else {
			return err
		}
	}
	raw, err := a.call(ctx, "POST", "/api/vpn/device/register", a.deviceBody())
	if err != nil {
		return err
	}
	var cfg struct {
		Password string   `json:"wdtt_password"`
		Hashes   []string `json:"vk_hashes"`
		IP       string   `json:"server_ip"`
		Port     int      `json:"server_port"`
		ID       string   `json:"device_id"`
		Streams  int      `json:"stream_count"`
		DNS      string   `json:"wg_dns"`
	}
	if err = json.Unmarshal(raw, &cfg); err != nil {
		return err
	}
	if cfg.Password == "" || len(cfg.Hashes) == 0 || net.ParseIP(cfg.IP).To4() == nil || cfg.Port < 1 || cfg.Port > 65535 || cfg.ID == "" {
		return errors.New("Сервер вернул неполные настройки транспорта")
	}
	if cfg.Streams < 1 || cfg.Streams > 16 {
		cfg.Streams = 9
	}
	turnPath := filepath.Join(filepath.Dir(a.path), "wg-turn.conf")
	_ = os.Remove(turnPath)
	proc := exec.Command(filepath.Join(a.root, "spass"), "-peer", net.JoinHostPort(cfg.IP, fmt.Sprint(cfg.Port)), "-vk", strings.Join(cfg.Hashes, ","), "-password", cfg.Password, "-device-id", cfg.ID, "-listen", "127.0.0.1:9000", "-n", fmt.Sprint(cfg.Streams))
	proc.Dir = filepath.Dir(a.path)
	proc.Env = append(os.Environ(), "GOMAXPROCS=2")
	if err = proc.Start(); err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- proc.Wait() }()
	a.stopTunnel = func() {
		_ = proc.Process.Kill()
		select {
		case <-done:
		case <-time.After(3 * time.Second):
		}
		_ = os.Remove(turnPath)
	}
	var wc wgConfig
	for {
		if text, e := os.ReadFile(turnPath); e == nil {
			wc, e = parseWG(string(text))
			if e == nil {
				break
			}
		}
		select {
		case e := <-done:
			return fmt.Errorf("Транспорт завершился до готовности: %v", e)
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	native, err := tun.CreateTUN(iface, wc.MTU)
	if err != nil {
		return fmt.Errorf("TUN: %w", err)
	}
	wg := device.NewDevice(native, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	stopTransport := a.stopTunnel
	a.stopTunnel = func() { wg.Close(); stopTransport() }
	if err = wg.IpcSet(wc.IPC); err != nil {
		return err
	}
	if err = wg.Up(); err != nil {
		return err
	}
	if err = a.network(ctx, "prepare", wc.Address, fmt.Sprint(wc.MTU)); err != nil {
		return err
	}
	for {
		state, e := wg.IpcGet()
		if e != nil {
			return e
		}
		if handshakeReady(state) {
			break
		}
		select {
		case e := <-done:
			return fmt.Errorf("Транспорт завершился: %v", e)
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Second):
		}
	}
	if err = a.network(ctx, "ready"); err != nil {
		return fmt.Errorf("Шлюз туннеля недоступен: %w", err)
	}
	a.mu.RLock()
	preset, custom := a.cfg.DNSPreset, a.cfg.DNSCustom
	a.mu.RUnlock()
	dnsText := wc.DNS
	if dnsText == "" {
		dnsText = cfg.DNS
	}
	if dnsText == "" {
		dnsText = "1.1.1.1,1.0.0.1"
	}
	if preset == "custom" {
		dnsText = custom
	}
	upstream, err := dnsAddresses(dnsText)
	if err != nil {
		return err
	}
	a.mu.Lock()
	a.upstream = upstream
	a.wgAddress = strings.Split(wc.Address, "/")[0]
	a.mu.Unlock()
	if err = a.startDNS(); err != nil {
		return err
	}
	if _, err = a.call(ctx, "POST", "/api/vpn/connect", map[string]string{"device_fingerprint": a.cfg.Fingerprint, "device_type": "pc"}); err != nil {
		return err
	}
	if err = a.network(ctx, "up"); err != nil {
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	a.mu.Lock()
	a.connected = true
	a.cfg.Reconnect = true
	a.mu.Unlock()
	if err = a.persist(); err != nil {
		return err
	}
	return nil
}

func (a *Agent) watch(ctx context.Context) {
	tick := time.NewTicker(20 * time.Second)
	defer tick.Stop()
	failures := 0
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			if !a.isConnected() {
				failures = 0
				continue
			}
			probe, cancel := context.WithTimeout(ctx, 8*time.Second)
			_, err := a.call(probe, "GET", "/api/vpn/theme", nil)
			cancel()
			if err == nil {
				restore, cancel := context.WithTimeout(ctx, 10*time.Second)
				err = a.network(restore, "ensure")
				cancel()
			}
			if err == nil {
				failures = 0
				continue
			}
			failures++
			if failures < 3 {
				continue
			}
			a.interrupt()
			a.op.Lock()
			a.disconnect()
			a.op.Unlock()
			failures = 0
		}
	}
}
