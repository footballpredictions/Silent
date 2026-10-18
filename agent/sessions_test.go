package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSessionActionsUseLiveTunnelWhenPublicAPIIsBlocked(t *testing.T) {
	a := testAgent(t)
	a.cfg.Token = "fixture-token"
	a.connected = true
	a.pathReady = func() bool { return true }
	visited := []string{}
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "10.66.66.1:8000" || r.Header.Get("Authorization") != "Bearer fixture-token" {
			t.Fatalf("session action left live tunnel: %s", r.URL)
		}
		visited = append(visited, r.Method+" "+r.URL.Path)
		if r.Method == "PATCH" {
			var body map[string]string
			if json.NewDecoder(r.Body).Decode(&body) != nil || body["device_name"] != "TV renamed" {
				t.Fatal("rename body changed")
			}
		}
		w := httptest.NewRecorder()
		_, _ = w.Write([]byte(`{"ok":true,"email":"fixture@example.test","devices":[{"id":"other","is_connected":true}]}`))
		return w.Result(), nil
	})
	for _, tc := range []struct{ method, op, body string }{
		{"GET", "profile", ""},
		{"POST", "device-rename", `{"id":"other","name":"TV renamed"}`},
		{"POST", "device-delete", `{"id":"other"}`},
	} {
		w := httptest.NewRecorder()
		a.serveAPI(w, httptest.NewRequest(tc.method, "/cgi-bin/silent-api/"+tc.op, strings.NewReader(tc.body)))
		if w.Code != 200 {
			t.Fatalf("%s: HTTP%d %s", tc.op, w.Code, w.Body.String())
		}
	}
	if strings.Join(visited, ",") != "GET /api/users/me,PATCH /api/users/devices/other,DELETE /api/users/devices/other" {
		t.Fatal(visited)
	}
	if !a.connected || a.cfg.Token != "fixture-token" {
		t.Fatal("session action changed live connection")
	}
}

func TestSessionActionsRejectInvalidIdentifiersAndMissingLogin(t *testing.T) {
	a := testAgent(t)
	for _, tc := range []struct {
		token, body string
		code        int
	}{
		{"fixture", `{"id":"../admin"}`, 400},
		{"fixture", `{"id":""}`, 400},
		{"", `{"id":"other"}`, 401},
	} {
		a.cfg.Token = tc.token
		w := httptest.NewRecorder()
		a.serveAPI(w, httptest.NewRequest("POST", "/cgi-bin/silent-api/device-delete", strings.NewReader(tc.body)))
		if w.Code != tc.code {
			t.Fatalf("HTTP%d, want %d", w.Code, tc.code)
		}
	}
}

func TestExpiredSessionRefreshesAndRetriesInsideVPN(t *testing.T) {
	for _, method := range []string{"GET", "PATCH", "DELETE"} {
		t.Run(method, func(t *testing.T) {
			a := testAgent(t)
			a.cfg.Token, a.cfg.RefreshToken = "expired", "fixture-refresh"
			a.connected = true
			a.pathReady = func() bool { return true }
			calls := []string{}
			a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if r.URL.Host != "10.66.66.1:8000" {
					t.Fatal("session left VPN")
				}
				calls = append(calls, r.Method+" "+r.URL.Path)
				w := httptest.NewRecorder()
				if r.URL.Path == "/api/auth/refresh" {
					_, _ = w.Write([]byte(`{"access_token":"fresh","refresh_token":"fixture-refresh"}`))
				} else if r.Header.Get("Authorization") == "Bearer fresh" {
					_, _ = w.Write([]byte(`{"ok":true}`))
				} else {
					w.WriteHeader(401)
					_, _ = w.Write([]byte(`{"detail":"expired"}`))
				}
				return w.Result(), nil
			})
			if _, err := a.callSession(t.Context(), method, "/api/users/devices/other", nil); err != nil {
				t.Fatal(err)
			}
			if len(calls) != 3 || calls[1] != "POST /api/auth/refresh" {
				t.Fatal(calls)
			}
		})
	}
}

func TestPendingRefreshDoesNotRestoreClosedLogin(t *testing.T) {
	a := testAgent(t)
	a.cfg.Token, a.cfg.RefreshToken = "expired", "fixture-refresh"
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		a.mu.Lock()
		a.cfg.Token, a.cfg.RefreshToken = "", ""
		a.mu.Unlock()
		w := httptest.NewRecorder()
		_, _ = w.Write([]byte(`{"access_token":"fresh","refresh_token":"fixture-refresh"}`))
		return w.Result(), nil
	})
	if err := a.refresh(t.Context()); err != nil {
		t.Fatal(err)
	}
	if a.cfg.Token != "" || a.cfg.RefreshToken != "" {
		t.Fatal("pending refresh resurrected logout")
	}
}
