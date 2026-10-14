package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type routingPolicy struct {
	Schema   int      `json:"schema_version"`
	Revision string   `json:"revision"`
	Direct   []string `json:"direct_domains"`
	VPN      []string `json:"vpn_domains"`
}

func validDomain(s string) bool {
	if len(s) == 0 || len(s) > 253 || net.ParseIP(s) != nil {
		return false
	}
	for _, label := range strings.Split(s, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
				return false
			}
		}
	}
	return strings.Contains(s, ".") || s == "ru" || s == "su" || s == "xn--p1ai"
}

func parsePolicy(raw []byte) (routingPolicy, error) {
	var p routingPolicy
	if len(raw) > 262144 || json.Unmarshal(raw, &p) != nil {
		return p, fmt.Errorf("Некорректная политика обхода")
	}
	hash, err := hex.DecodeString(p.Revision)
	if p.Schema != 1 || err != nil || len(hash) != 32 || p.Revision != strings.ToLower(p.Revision) || p.Direct == nil || p.VPN == nil || len(p.Direct) > 2000 || len(p.VPN) > 2000 {
		return p, fmt.Errorf("Некорректная политика обхода")
	}
	for _, list := range [][]string{p.Direct, p.VPN} {
		for _, d := range list {
			if !validDomain(d) {
				return p, fmt.Errorf("Некорректный домен обхода")
			}
		}
	}
	return p, nil
}

func writePrivate(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	if err := os.WriteFile(path+".new", data, 0600); err != nil {
		return err
	}
	return os.Rename(path+".new", path)
}

func packagedDomains(path string) []string {
	b, _ := os.ReadFile(path)
	var result []string
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if validDomain(line) {
			result = append(result, line)
		}
	}
	return result
}

func (a *Agent) loadPolicy() {
	a.domains = packagedDomains(filepath.Join(a.root, "ru-direct.domains"))
	a.vpnDomains = packagedDomains(filepath.Join(a.root, "ru-vpn.domains"))
	if b, err := os.ReadFile(filepath.Join(filepath.Dir(a.path), "routing-policy.json")); err == nil {
		if p, err := parsePolicy(b); err == nil {
			a.domains, a.vpnDomains, a.policyRevision = p.Direct, p.VPN, p.Revision
		}
	}
}

// Called with op held, so a policy change cannot race a connect/disconnect.
func (a *Agent) refreshPolicy(ctx context.Context) {
	a.mu.RLock()
	enabled := a.cfg.Direct
	a.mu.RUnlock()
	if !enabled || time.Since(a.lastPolicy) < 300*time.Second {
		return
	}
	a.lastPolicy = time.Now()
	for _, base := range a.apiBases() {
		raw, err := a.callBases(ctx, []string{base}, "GET", "/api/vpn/routing-policy", nil)
		if err != nil {
			continue
		}
		p, err := parsePolicy(raw)
		if err != nil {
			continue
		}
		if p.Revision == a.policyRevision {
			return
		}
		a.policyMu.Lock()
		if a.isConnected() {
			for _, set := range []string{"svk_direct", "svk_vpn"} {
				if err = a.run(ctx, "ipset", "flush", set); err != nil {
					break
				}
			}
		}
		if err == nil {
			err = writePrivate(filepath.Join(filepath.Dir(a.path), "routing-policy.json"), raw)
		}
		if err == nil {
			a.domains, a.vpnDomains, a.policyRevision = p.Direct, p.VPN, p.Revision
			a.learnedMu.Lock()
			a.learnedDirect, a.learnedVPN = nil, nil
			a.learnedMu.Unlock()
		}
		a.policyMu.Unlock()
		return
	}
}

func (a *Agent) restoreLearned(ctx context.Context) error {
	a.policyMu.RLock()
	defer a.policyMu.RUnlock()
	a.learnedMu.Lock()
	defer a.learnedMu.Unlock()
	var input strings.Builder
	for set, values := range map[string]map[string]bool{"svk_direct": a.learnedDirect, "svk_vpn": a.learnedVPN} {
		for ip := range values {
			if parsed := net.ParseIP(ip); parsed == nil || parsed.To4() == nil {
				return fmt.Errorf("Некорректный cached IP")
			}
			fmt.Fprintf(&input, "add %s %s -exist\n", set, ip)
		}
	}
	if input.Len() == 0 {
		return nil
	}
	if a.restoreSets != nil {
		return a.restoreSets(ctx, input.String())
	}
	cmd := exec.CommandContext(ctx, "ipset", "restore", "-exist")
	cmd.Env = append(os.Environ(), "PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin")
	cmd.Stdin = strings.NewReader(input.String())
	return cmd.Run()
}
