package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCatalogPolicyRefreshPreservesExactNamesThroughCache(t *testing.T) {
	a := testAgent(t)
	a.cfg.Direct = true
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("profile") != "catalog-test" {
			t.Error("merged profile not requested")
		}
		_, _ = w.Write([]byte(`{"schema_version":1,"profile":"catalog-test","revision":"` + strings.Repeat("a", 64) + `","direct_domains":["service.ru"],"direct_exact_domains":["exact.test"],"vpn_domains":["force.service.ru"]}`))
	}))
	defer server.Close()
	a.bases = []string{server.URL}
	a.refreshPolicy(context.Background())
	if len(a.exactDomains) != 1 || a.exactDomains[0] != "exact.test" {
		t.Fatal("exact list lost during refresh")
	}
	b := testAgent(t)
	b.path = filepath.Join(filepath.Dir(a.path), "config.json")
	b.root = t.TempDir()
	b.loadPolicy()
	if len(b.exactDomains) != 1 || b.exactDomains[0] != "exact.test" {
		t.Fatal("exact list lost from cache")
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(a.path), "routing-policy.json")); err != nil {
		t.Fatal(err)
	}
	a.cfg.RoutingProfile = "standard"
	if a.routingPolicyPath() != "/api/vpn/routing-policy" {
		t.Fatal("legacy override unavailable")
	}
}

func TestAdditivePolicyKeepsExistingClientRoutes(t *testing.T) {
	a := testAgent(t)
	a.cfg.Direct, a.connected = true, true
	a.domains = []string{"service.ru"}
	a.vpnDomains = []string{"force.service.ru"}
	a.policyRevision = strings.Repeat("a", 64)
	a.learnedDirect = map[string]bool{"192.0.2.7": true}
	a.learnedVPN = map[string]bool{"198.51.100.7": true}
	var commands []string
	a.run = func(_ context.Context, cmd string, args ...string) error {
		commands = append(commands, cmd+" "+strings.Join(args, " "))
		return nil
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"schema_version":1,"revision":"` + strings.Repeat("b", 64) + `","direct_domains":["service.ru","newly-added.ru"],"vpn_domains":["force.service.ru"]}`))
	}))
	defer server.Close()
	a.bases = []string{server.URL}
	a.refreshPolicy(context.Background())
	if len(commands) != 0 {
		t.Fatalf("additive policy interrupted existing routes: %v", commands)
	}
	var restored string
	a.restoreSets = func(_ context.Context, data string) error { restored = data; return nil }
	if err := a.restoreLearned(context.Background()); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"svk_direct 192.0.2.7", "svk_vpn 198.51.100.7"} {
		if !strings.Contains(restored, want) {
			t.Fatal(fmt.Sprintf("cached client route not restored (%s): %s", want, restored))
		}
	}
}
