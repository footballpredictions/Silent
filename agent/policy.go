package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"silent-keenetic/routerpolicy"
	"strings"
	"time"
)

type routingPolicy = routerpolicy.Policy

func (a *Agent) routingPolicyPath() string {
	a.mu.RLock()
	profile := a.cfg.RoutingProfile
	a.mu.RUnlock()
	if profile == "standard" {
		return "/api/vpn/routing-policy"
	}
	return "/api/vpn/routing-policy?profile=catalog-test"
}

func validDomain(s string) bool                     { return routerpolicy.ValidDomain(s) }
func parsePolicy(raw []byte) (routingPolicy, error) { return routerpolicy.Parse(raw) }

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
			a.domains, a.exactDomains, a.vpnDomains, a.policyRevision = p.Direct, p.Exact, p.VPN, p.Revision
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
		raw, err := a.callBases(ctx, []string{base}, "GET", a.routingPolicyPath(), nil)
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
			a.domains, a.exactDomains, a.vpnDomains, a.policyRevision = p.Direct, p.Exact, p.VPN, p.Revision
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
