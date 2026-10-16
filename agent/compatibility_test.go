package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestConnectedAPIFallsBackAfterTunnelProxyFailure(t *testing.T) {
	for _, ready := range []bool{true, false} {
		t.Run(fmt.Sprint(ready), func(t *testing.T) {
			a := testAgent(t)
			a.connected = true
			a.pathReady = func() bool { return ready }
			a.bases = []string{"http://backup.example"}
			var visited []string
			a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				visited = append(visited, r.URL.Host)
				w := httptest.NewRecorder()
				if strings.Contains(r.URL.Host, "10.66.66.1") {
					w.WriteHeader(503)
					_, _ = w.Write([]byte(`{"detail":"busy"}`))
				} else {
					_, _ = w.Write([]byte(`{"ok":true}`))
				}
				return w.Result(), nil
			})
			if _, err := a.call(context.Background(), "POST", "/api/vpn/device/register", map[string]string{"device_fingerprint": "same"}); err != nil {
				t.Fatal(err)
			}
			want := []string{"backup.example"}
			if ready {
				want = append([]string{"10.66.66.1:8000"}, want...)
			}
			if fmt.Sprint(visited) != fmt.Sprint(want) {
				t.Fatal(visited, want)
			}
		})
	}
}

func TestNonJSONAccessFailuresRemainAuthoritative(t *testing.T) {
	for _, code := range []int{401, 402, 403} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			a := testAgent(t)
			a.bases = []string{"http://first.example", "http://backup.example"}
			calls := 0
			a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				calls++
				w := httptest.NewRecorder()
				w.WriteHeader(code)
				_, _ = w.Write([]byte("<html>Denied</html>"))
				return w.Result(), nil
			})
			_, err := a.call(context.Background(), "GET", "/api/users/me", nil)
			if err == nil || calls != 1 {
				t.Fatalf("access denial bypassed: %v calls %d", err, calls)
			}
		})
	}
}

func policyData(direct, vpn []string) []byte {
	b, _ := json.Marshal(routingPolicy{Schema: 1, Revision: strings.Repeat("a", 64), Direct: direct, VPN: vpn})
	return b
}
func TestPolicyRejectsMalformedAndOversizedLists(t *testing.T) {
	for _, b := range [][]byte{[]byte(`{}`), policyData(nil, []string{}), policyData([]string{"ru; reboot"}, []string{}), policyData([]string{"EXAMPLE.com"}, []string{}), policyData([]string{"1.1.1.1"}, []string{}), policyData(make([]string, 2001), []string{})} {
		if _, err := parsePolicy(b); err == nil {
			t.Fatal("unsafe policy accepted")
		}
	}
	if _, err := parsePolicy(policyData([]string{}, []string{})); err != nil {
		t.Fatal("empty administrator lists are valid", err)
	}
}
func TestPolicyCachesLastGoodAndKeepsItWhenOffline(t *testing.T) {
	a := testAgent(t)
	a.cfg.Direct = true
	a.root = t.TempDir()
	_ = os.WriteFile(filepath.Join(a.root, "ru-direct.domains"), []byte("ru\n"), 0600)
	_ = os.WriteFile(filepath.Join(a.root, "ru-vpn.domains"), []byte("youtube.com\n"), 0600)
	a.loadPolicy()
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		w := httptest.NewRecorder()
		_, _ = w.Write(policyData([]string{"example.ru"}, []string{"video.example.ru"}))
		return w.Result(), nil
	})
	a.refreshPolicy(context.Background())
	if !suffixMatch("cdn.video.example.ru", a.vpnDomains) || !suffixMatch("example.ru", a.domains) {
		t.Fatal("policy not applied")
	}
	copy := testAgent(t)
	copy.path = a.path
	copy.root = a.root
	copy.loadPolicy()
	if copy.policyRevision != strings.Repeat("a", 64) || fmt.Sprint(copy.domains) != "[example.ru]" {
		t.Fatal("last good policy not loaded")
	}
	a.lastPolicy = a.lastPolicy.Add(-301000000000)
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) { return nil, fmt.Errorf("offline") })
	a.refreshPolicy(context.Background())
	if fmt.Sprint(a.domains) != "[example.ru]" {
		t.Fatal("offline policy lost")
	}
}
func TestPolicyRefreshFlushesOnlyOwnedSetsOnRevisionChange(t *testing.T) {
	a := testAgent(t)
	a.cfg.Direct = true
	a.connected = true
	a.pathReady = func() bool { return false }
	a.learnedDirect = map[string]bool{"1.2.3.4": true}
	a.learnedVPN = map[string]bool{"5.6.7.8": true}
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		w := httptest.NewRecorder()
		_, _ = w.Write(policyData([]string{"ru"}, []string{"video.ru"}))
		return w.Result(), nil
	})
	var commands []string
	a.run = func(ctx context.Context, command string, args ...string) error {
		commands = append(commands, command+" "+strings.Join(args, " "))
		return nil
	}
	a.refreshPolicy(context.Background())
	want := "[ipset flush svk_direct ipset flush svk_vpn]"
	if fmt.Sprint(commands) != want || len(a.learnedDirect) != 0 || len(a.learnedVPN) != 0 {
		t.Fatal(commands, a.learnedDirect)
	}
	a.lastPolicy = a.lastPolicy.Add(-301000000000)
	a.refreshPolicy(context.Background())
	if len(commands) != 2 {
		t.Fatal("unchanged policy flushed DNS caches")
	}
}
func TestLearnedIPsRestoredWithoutExpiration(t *testing.T) {
	a := testAgent(t)
	a.learnedDirect = map[string]bool{"1.2.3.4": true}
	a.learnedVPN = map[string]bool{"5.6.7.8": true}
	var input string
	a.restoreSets = func(ctx context.Context, data string) error {
		input = data
		return nil
	}
	if err := a.restoreLearned(context.Background()); err != nil {
		t.Fatal(err)
	}
	joined := input
	if !strings.Contains(joined, "svk_direct 1.2.3.4 -exist") || !strings.Contains(joined, "svk_vpn 5.6.7.8 -exist") || strings.Contains(joined, "timeout") {
		t.Fatal(joined)
	}
}

func TestReconnectRestoresBypassBeforeRedirectingLAN(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		a := testAgent(t)
		a.cfg.Direct = enabled
		a.learnedDirect = map[string]bool{"192.0.2.7": true}
		var events []string
		a.restoreSets = func(ctx context.Context, data string) error {
			events = append(events, "restore")
			if !strings.Contains(data, "svk_direct 192.0.2.7 -exist") {
				t.Fatal(data)
			}
			return nil
		}
		a.run = func(ctx context.Context, name string, args ...string) error {
			events = append(events, "redirect")
			return nil
		}
		if err := a.network(context.Background(), "up"); err != nil {
			t.Fatal(err)
		}
		want := "[redirect]"
		if enabled {
			want = "[restore redirect]"
		}
		if fmt.Sprint(events) != want {
			t.Fatal(enabled, events)
		}
	}
}

func TestReconnectStopsBeforeLANIfBypassRestoreFails(t *testing.T) {
	a := testAgent(t)
	a.cfg.Direct = true
	a.learnedDirect = map[string]bool{"192.0.2.7": true}
	a.restoreSets = func(ctx context.Context, data string) error { return fmt.Errorf("restore failed") }
	a.run = func(ctx context.Context, name string, args ...string) error {
		t.Fatal("LAN redirected without bypass")
		return nil
	}
	if err := a.network(context.Background(), "up"); err == nil {
		t.Fatal("bypass failure reported as success")
	}
}

func TestUpdateStartRequiresSilentAccount(t *testing.T) {
	a := testAgent(t)
	r := httptest.NewRequest("POST", "http://192.168.1.1:8787/cgi-bin/silent-api/update-start", strings.NewReader(`{}`))
	r.RemoteAddr = "192.168.1.2:12345"
	r.SetBasicAuth("admin", a.cfg.AdminPassword)
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal(w.Code, w.Body.String())
	}
	if _, err := os.Stat(updateLock(a.path)); !os.IsNotExist(err) {
		t.Fatal("worker started without account")
	}
}
