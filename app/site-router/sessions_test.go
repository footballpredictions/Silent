//go:build linux || android

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSessionsRelayPreservesMethodsAuthAndBody(t *testing.T) {
	for _, tc := range []struct{ method, path, body string }{
		{"GET", "/api/users/me", ""},
		{"PATCH", "/api/users/devices/fixture-device", `{"device_name":"New name"}`},
		{"DELETE", "/api/users/devices/fixture-device", ""},
		{"POST", "/api/auth/refresh", `{"refresh_token":"fixture"}`},
	} {
		t.Run(tc.method+tc.path, func(t *testing.T) {
			transport := sessionsRoundTrip(func(r *http.Request) (*http.Response, error) {
				var body []byte
				if r.Body != nil {
					body, _ = io.ReadAll(r.Body)
				}
				if r.Method != tc.method || r.URL.Host != "10.66.66.1:8000" || r.Host != "10.66.66.1:8000" || r.URL.Path != tc.path || string(body) != tc.body || r.Header.Get("Authorization") != "Bearer fixture" {
					t.Errorf("request changed: %s %s host=%s body=%s", r.Method, r.URL, r.Host, body)
				}
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"devices":[{"id":"other","is_connected":true}]}`))}, nil
			})
			r := httptest.NewRequest(tc.method, "http://127.0.0.1:18766"+tc.path, strings.NewReader(tc.body))
			r.Header.Set("Authorization", "Bearer fixture")
			w := httptest.NewRecorder()
			otaHandler(transport).ServeHTTP(w, r)
			if w.Code != 200 || w.Header().Get("X-Silent-Upstream") != "1" || !strings.Contains(w.Body.String(), `"other"`) {
				t.Fatalf("sessions unreachable through live VPN: HTTP%d %s", w.Code, w.Body.String())
			}
		})
	}
}

type sessionsRoundTrip func(*http.Request) (*http.Response, error)

func (f sessionsRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestSessionsRelayRejectsUnrelatedWrites(t *testing.T) {
	for _, path := range []string{"/api/users/devices", "/api/users/devices/a/b", "/api/admin/users", "/api/payments/init", "/api/users/me"} {
		w := httptest.NewRecorder()
		otaHandler(sessionsRoundTrip(func(*http.Request) (*http.Response, error) { t.Fatal("unrelated write forwarded"); return nil, nil })).ServeHTTP(w, httptest.NewRequest("POST", path, nil))
		if w.Code != 403 {
			t.Errorf("%s: HTTP%d", path, w.Code)
		}
	}
}
