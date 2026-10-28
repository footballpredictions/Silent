package main

import (
	"context"
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
