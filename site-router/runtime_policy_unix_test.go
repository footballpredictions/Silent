//go:build linux || darwin

package main

import (
	"encoding/json"
	"net"
	"path/filepath"
	"slices"
	"testing"
)

func TestUnixPolicySocketPreservesApplicationsAndResolverGuards(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "policy.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	adapter := &routedTun{routes: make(map[flow]cachedRoute), dnsProxy: newTunnelDNS()}
	adapter.policy.Store(newProcessPolicy(policyConfig{}))
	go servePolicy(listener, adapter)
	client, err := net.Dial("unix", listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	cfg := policyConfig{Excluded: []string{"fixture-app"}, DNS: []string{"9.9.9.9"}, Russian: russianConfig{Enabled: true}}
	if err := json.NewEncoder(client).Encode(cfg); err != nil {
		t.Fatal(err)
	}
	var ack struct {
		OK bool `json:"ok"`
	}
	if err := json.NewDecoder(client).Decode(&ack); err != nil || !ack.OK {
		t.Fatal("native ACK missing", err)
	}
	actual := adapter.policy.Load()
	if !slices.Equal(actual.excluded, cfg.Excluded) || !slices.Equal(actual.dns, cfg.DNS) {
		t.Fatal("Application or DNS guard was dropped at Unix socket", actual.excluded, actual.dns)
	}
}
