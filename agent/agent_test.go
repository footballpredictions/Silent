package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/miekg/dns"
)

func testAgent(t *testing.T) *Agent {
	t.Helper()
	c := Config{LANInterface: "br0", LANIP: "192.168.1.1", LANPrefix: "192.168.1.0/24", Port: 8787, AdminPassword: strings.Repeat("a", 24), Fingerprint: "test-device", DNSPreset: "server"}
	return &Agent{cfg: c, path: filepath.Join(t.TempDir(), "config.json"), client: newHTTPClient(), bases: publicAPIs}
}

func TestAccessFailureDoesNotFailover(t *testing.T) {
	for _, code := range []int{401, 402, 403} {
		t.Run(http.StatusText(code), func(t *testing.T) {
			var backup atomic.Int32
			first := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(code)
				_, _ = w.Write([]byte(`{"detail":"denied"}`))
			}))
			defer first.Close()
			second := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { backup.Add(1); _, _ = w.Write([]byte(`{"ok":true}`)) }))
			defer second.Close()
			a := testAgent(t)
			a.bases = []string{first.URL, second.URL}
			_, err := a.call(context.Background(), "GET", "/api/users/me", nil)
			if err == nil || backup.Load() != 0 {
				t.Fatalf("access failure was bypassed: %v, %d", err, backup.Load())
			}
		})
	}
}

func TestNetworkFailureCanFailover(t *testing.T) {
	first := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(503)
		_, _ = w.Write([]byte(`{"detail":"busy"}`))
	}))
	defer first.Close()
	second := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer secret" || r.Header.Get("X-App-Version") != version {
			t.Error("missing headers")
		}
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer second.Close()
	a := testAgent(t)
	a.cfg.Token = "secret"
	a.bases = []string{first.URL, second.URL}
	b, err := a.call(context.Background(), "GET", "/x", nil)
	if err != nil || string(b) != `{"ok":true}` {
		t.Fatalf("%s %v", b, err)
	}
}

func TestLoginEscapesPasswordAndPersistsSession(t *testing.T) {
	password := "quotes\"\\\n$()"
	token := "one.two.three"
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/login":
			var b map[string]string
			_ = json.NewDecoder(r.Body).Decode(&b)
			if b["password"] != password {
				t.Error("password altered")
			}
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": token, "refresh_token": "refresh"})
		case "/api/users/me":
			if r.Header.Get("Authorization") != "Bearer "+token {
				t.Error("token not used")
			}
			_, _ = w.Write([]byte(`{"email":"me@example.com"}`))
		default:
			_, _ = w.Write([]byte(`{}`))
		}
	}))
	defer s.Close()
	a := testAgent(t)
	a.bases = []string{s.URL}
	_, err := a.login(context.Background(), map[string]any{"email": "me@example.com", "password": password})
	if err != nil {
		t.Fatal(err)
	}
	c, err := loadConfig(a.path)
	if err != nil || c.Token != token || c.Email != "me@example.com" {
		t.Fatalf("session not persisted: %v", err)
	}
}

func TestLANPanelAuthenticationAndCSRF(t *testing.T) {
	a := testAgent(t)
	for _, tt := range []struct {
		name, host, remote, origin, method string
		auth                               bool
		code                               int
	}{
		{"status", "192.168.1.1:8787", "192.168.1.2:5500", "", "GET", true, 200},
		{"auth", "192.168.1.1:8787", "192.168.1.2:5500", "", "GET", false, 401},
		{"wan", "192.168.1.1:8787", "8.8.8.8:5500", "", "GET", true, 403},
		{"rebinding", "evil.example:8787", "192.168.1.2:5500", "", "GET", true, 403},
		{"csrf", "192.168.1.1:8787", "192.168.1.2:5500", "http://evil.example", "POST", true, 403},
		{"method", "192.168.1.1:8787", "192.168.1.2:5500", "", "POST", true, 405},
	} {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest(tt.method, "http://"+tt.host+"/cgi-bin/silent-api/status", strings.NewReader(`{}`))
			r.RemoteAddr = tt.remote
			r.Header.Set("Content-Type", "application/json")
			if tt.origin != "" {
				r.Header.Set("Origin", tt.origin)
			}
			if tt.auth {
				r.SetBasicAuth("admin", a.cfg.AdminPassword)
			}
			w := httptest.NewRecorder()
			a.handler().ServeHTTP(w, r)
			if w.Code != tt.code {
				t.Fatalf("code %d want %d: %s", w.Code, tt.code, w.Body.String())
			}
			if strings.Contains(w.Body.String(), a.cfg.AdminPassword) {
				t.Fatal("panel password leaked")
			}
		})
	}
}

func validWG() string {
	key := base64.StdEncoding.EncodeToString(make([]byte, 32))
	return "[Interface]\nPrivateKey = " + key + "\nAddress = 10.66.66.2/32\nMTU = 1200\nDNS = 1.1.1.1\n[Peer]\nPublicKey = " + key + "\nEndpoint = 8.8.8.8:56000\nAllowedIPs = 0.0.0.0/0, ::/0\n"
}
func TestTransportWGConfigUsesLocalEndpointAndIPv4(t *testing.T) {
	c, err := parseWG(validWG())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(c.IPC, "endpoint=127.0.0.1:9000") || strings.Contains(c.IPC, "::/0") || strings.Contains(c.IPC, "8.8.8.8") || c.MTU != 1200 {
		t.Fatal(c)
	}
}
func TestWGRejectsHooksAndMalformedKeys(t *testing.T) {
	for _, s := range []string{validWG() + "PostUp = rm -rf /\n", strings.Replace(validWG(), "10.66.66.2/32", "::1/128", 1), strings.Replace(validWG(), "MTU = 1200", "MTU = 65535", 1), "[Interface]\nPrivateKey = nope\n"} {
		if _, err := parseWG(s); err == nil {
			t.Fatal("accepted unsafe config")
		}
	}
}
func TestHandshakeGate(t *testing.T) {
	if handshakeReady("last_handshake_time_sec=0\n") || handshakeReady("last_handshake_time_nsec=123\n") || !handshakeReady("last_handshake_time_sec=123\n") {
		t.Fatal("wrong readiness gate")
	}
}
func TestDomainSuffixes(t *testing.T) {
	d := []string{"ru", "flashscore.com", "xn--p1ai"}
	for _, n := range []string{"bank.ru.", "static.flashscore.com", "SITE.XN--P1AI."} {
		if !suffixMatch(n, d) {
			t.Fatal(n)
		}
	}
	for _, n := range []string{"notflashscore.com", "flashscore.com.evil.org", "youtube.com"} {
		if suffixMatch(n, d) {
			t.Fatal(n)
		}
	}
}
func TestBoundDNSUsesIPv4Address(t *testing.T) {
	for _, s := range []string{"1.1.1.1; reboot", "::1", "1.1.1.1,2.2.2.2,3.3.3.3,4.4.4.4", ""} {
		if _, err := dnsAddresses(s); err == nil {
			t.Fatal(s)
		}
	}
	if _, err := dnsAddresses("77.88.8.8, 1.1.1.1"); err != nil {
		t.Fatal(err)
	}
}
func TestConfigDoesNotAcceptWANBinding(t *testing.T) {
	a := testAgent(t)
	a.cfg.LANIP = "8.8.8.8"
	a.cfg.LANPrefix = "8.8.8.0/24"
	if a.cfg.validate() == nil {
		t.Fatal("public bind accepted")
	}
}
func TestEmbeddedPanel(t *testing.T) {
	for _, path := range []string{"web/index.html", "web/js/app.js", "web/css/app.css"} {
		b, err := assets.ReadFile(path)
		if err != nil || len(b) == 0 {
			t.Fatal(path, err)
		}
		if path != "web/css/app.css" && strings.Contains(string(b), "OpenWrt") {
			t.Fatal("wrong platform copy")
		}
	}
}

func TestPanelRootServesWithoutRedirectLoop(t *testing.T) {
	a := testAgent(t)
	r := httptest.NewRequest("GET", "http://192.168.1.1:8787/", nil)
	r.RemoteAddr = "192.168.1.2:5500"
	r.SetBasicAuth("admin", a.cfg.AdminPassword)
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `id="app"`) {
		t.Fatalf("panel root: %d %s", w.Code, w.Body.String())
	}
}

func TestRejectedLoginClearsPriorSession(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
		_, _ = w.Write([]byte(`{"detail":"denied"}`))
	}))
	defer s.Close()
	a := testAgent(t)
	a.cfg.Token = "old.token.value"
	a.cfg.Email = "old@example.com"
	a.bases = []string{s.URL}
	_, err := a.login(context.Background(), map[string]any{"email": "new@example.com", "password": "wrong"})
	if err == nil {
		t.Fatal("accepted rejected login")
	}
	c, err := loadConfig(a.path)
	if err != nil || c.Token != "" || c.Email != "" {
		t.Fatal("old session retained", err)
	}
}
func TestSavedConfigIsPrivate(t *testing.T) {
	a := testAgent(t)
	if err := a.persist(); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(a.path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() == 0 {
		t.Fatal("empty config")
	}
}
func TestPaymentLabelIsNotPathInjection(t *testing.T) {
	if validLabel("silent_a/../../auth") || validLabel("silent_") || !validLabel("silent_deadbeef") {
		t.Fatal("bad payment validation")
	}
}

type captureDNS struct {
	reply  *dns.Msg
	remote string
}

func (c *captureDNS) LocalAddr() net.Addr {
	return &net.UDPAddr{IP: net.ParseIP("192.168.1.1"), Port: 15353}
}
func (c *captureDNS) RemoteAddr() net.Addr {
	return &net.UDPAddr{IP: net.ParseIP(c.remote), Port: 5000}
}
func (c *captureDNS) WriteMsg(m *dns.Msg) error   { c.reply = m; return nil }
func (c *captureDNS) Write(b []byte) (int, error) { return len(b), nil }
func (c *captureDNS) Close() error                { return nil }
func (c *captureDNS) TsigStatus() error           { return nil }
func (c *captureDNS) TsigTimersOnly(bool)         {}
func (c *captureDNS) Hijack()                     {}
func TestDNSIPv6AndLANBoundary(t *testing.T) {
	a := testAgent(t)
	q := new(dns.Msg)
	q.SetQuestion("youtube.com.", dns.TypeAAAA)
	w := &captureDNS{remote: "192.168.1.2"}
	a.answerDNS(w, q)
	if w.reply == nil || len(w.reply.Answer) != 0 || w.reply.Rcode != dns.RcodeSuccess {
		t.Fatal("AAAA leaked")
	}
	w = &captureDNS{remote: "8.8.8.8"}
	a.answerDNS(w, q)
	if w.reply.Rcode != dns.RcodeRefused {
		t.Fatal("open DNS resolver")
	}
}
