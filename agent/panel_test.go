package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"slices"
	"strings"
	"testing"

	"github.com/miekg/dns"
)

func TestCanonicalPanelUsesAccountFormWithTrustedLANProxy(t *testing.T) {
	for _, tt := range []struct {
		name, remote, real, host, origin, site string
		method                                 string
		code                                   int
	}{
		{"panel", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "", "", "GET", 200},
		{"status", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn:80", "", "", "GET", 200},
		{"method", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "http://192.168.1.1.silent.vpn", "same-origin", "POST", 405},
		{"old-ndm-origin", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "http://192.168.1.1:8787", "same-origin", "POST", 405},
		{"old-ndm-ambiguous", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "http://192.168.1.1:8787", "", "POST", 403},
		{"forged-forwarded", "192.168.1.42:123", "192.168.1.43", "192.168.1.1.silent.vpn", "", "", "GET", 403},
		{"wan-proxy", "192.168.1.1:123", "8.8.8.8", "192.168.1.1.silent.vpn", "", "", "GET", 403},
		{"missing-real", "192.168.1.1:123", "", "192.168.1.1.silent.vpn", "", "", "GET", 403},
		{"ambiguous-real", "192.168.1.1:123", "192.168.1.42, 8.8.8.8", "192.168.1.1.silent.vpn", "", "", "GET", 403},
		{"rebinding", "192.168.1.1:123", "192.168.1.42", "evil.silent.vpn", "", "", "GET", 403},
		{"wrong-router", "192.168.1.1:123", "192.168.1.42", "192.168.2.1.silent.vpn", "", "", "GET", 403},
		{"csrf", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "http://evil.example", "cross-site", "POST", 403},
		{"rewritten-csrf", "192.168.1.1:123", "192.168.1.42", "192.168.1.1.silent.vpn", "http://192.168.1.1:8787", "cross-site", "POST", 403},
		{"legacy-still-authenticated", "192.168.1.42:123", "192.168.1.43", "192.168.1.1:8787", "", "", "GET", 401},
	} {
		t.Run(tt.name, func(t *testing.T) {
			a := testAgent(t)
			path := "/cgi-bin/silent-api/status"
			if tt.name == "panel" {
				path = "/"
			}
			r := httptest.NewRequest(tt.method, "http://"+tt.host+path, strings.NewReader(`{}`))
			r.RemoteAddr = tt.remote
			r.Header.Set("X-Real-IP", tt.real)
			r.Header.Set("Origin", tt.origin)
			r.Header.Set("Sec-Fetch-Site", tt.site)
			r.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			a.handler().ServeHTTP(w, r)
			if w.Code != tt.code {
				t.Fatalf("%d want %d: %s", w.Code, tt.code, w.Body.String())
			}
			if tt.code == 200 && w.Header().Get("WWW-Authenticate") != "" {
				t.Fatal("canonical panel requested a second login")
			}
		})
	}
}

func TestCanonicalPanelThroughRealHTTPReverseProxy(t *testing.T) {
	a := testAgent(t)
	// Loopback-only HTTP fixture; production configuration still requires a private LAN.
	a.cfg.LANIP = "127.0.0.1"
	a.cfg.LANPrefix = "127.0.0.0/8"
	backend := httptest.NewServer(a.handler())
	defer backend.Close()
	upstream, _ := url.Parse(backend.URL)
	proxy := httputil.NewSingleHostReverseProxy(upstream)
	original := proxy.Director
	proxy.Director = func(r *http.Request) { original(r); r.Host = panelHost(a.cfg); r.Header.Set("X-Real-IP", "127.0.0.2") }
	front := httptest.NewServer(proxy)
	defer front.Close()
	for _, path := range []string{"/", "/silent-vpn/css/app.css", "/silent-vpn/js/app.js", "/cgi-bin/silent-api/status"} {
		res, err := http.Get(front.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		body, _ := io.ReadAll(res.Body)
		res.Body.Close()
		if res.StatusCode != 200 || len(body) == 0 {
			t.Fatalf("%s: %d", path, res.StatusCode)
		}
		if path == "/cgi-bin/silent-api/status" && !strings.Contains(string(body), panelURL(a.cfg)) {
			t.Fatal("status advertises legacy port")
		}
	}
}

type panelNDM struct {
	settings []string
	records  []string
	foreign  string
	commands []string
	fail     string
	noOrigin bool
	port     string
}

func (n *panelNDM) run(_ context.Context, cmd string) ([]byte, error) {
	n.commands = append(n.commands, cmd)
	if cmd == "show running-config" {
		body := "ip host existing.local 192.168.1.50\nip http proxy unrelated\n domain static existing.local\n upstream http 192.168.1.50 9000\n!\n"
		if n.port != "" {
			body += "ip http port " + n.port + "\n"
		}
		for _, ip := range n.records {
			body += "ip host 192.168.1.1.silent.vpn " + ip + "\n"
		}
		if n.settings != nil {
			body += "ip http proxy " + panelProxy + "\n"
			for _, line := range n.settings {
				body += " " + line + "\n"
			}
			body += n.foreign + "!\n"
		}
		return []byte(body), nil
	}
	if cmd == n.fail {
		n.fail = ""
		return []byte("Command::Base: error: failed"), nil
	}
	if strings.HasSuffix(cmd, " preserve-origin") && n.noOrigin {
		return nil, errors.New("unsupported")
	}
	prefix := "ip http proxy " + panelProxy + " "
	switch {
	case strings.HasPrefix(cmd, prefix):
		setting := strings.TrimPrefix(cmd, prefix)
		if !slices.Contains(n.settings, setting) {
			n.settings = append(n.settings, setting)
		}
	case cmd == "no ip http proxy "+panelProxy:
		n.settings = nil
	case cmd == "ip host 192.168.1.1.silent.vpn 192.168.1.1":
		n.records = []string{"192.168.1.1"}
	case cmd == "no ip host 192.168.1.1.silent.vpn 192.168.1.1":
		n.records = nil
	case cmd == "system configuration save":
	default:
		return nil, fmt.Errorf("unexpected command: %s", cmd)
	}
	return []byte("OK"), nil
}
func TestPanelNDMLifecycleAndIdempotence(t *testing.T) {
	a := testAgent(t)
	n := &panelNDM{}
	a.ndmCommand = n.run
	if err := a.ensurePanel(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(n.records) != 1 || len(n.settings) != 6 {
		t.Fatalf("incomplete resources: %+v", n)
	}
	before := len(n.commands)
	if err := a.ensurePanel(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := n.commands[before:]; len(got) != 2 || got[0] != "show running-config" || got[1] != "show running-config" {
		t.Fatalf("repeated writes: %v", got)
	}
	if err := a.cleanupPanel(context.Background()); err != nil {
		t.Fatal(err)
	}
	if n.settings != nil || len(n.records) != 0 {
		t.Fatal("owned resources remained")
	}
	if _, err := os.Stat(a.bindingPath()); !os.IsNotExist(err) {
		t.Fatal("ownership marker remained")
	}
	for _, cmd := range n.commands {
		if strings.Contains(cmd, "unrelated") || strings.Contains(cmd, "existing.local") || strings.HasPrefix(cmd, "ip http port") || strings.Contains(cmd, "security-level public") {
			t.Fatalf("modified native/foreign config: %s", cmd)
		}
	}
}
func TestPanelNDMProtectsForeignResources(t *testing.T) {
	for _, mode := range []string{"foreign-proxy", "foreign-dns", "changed-proxy", "changed-dns", "custom-port"} {
		t.Run(mode, func(t *testing.T) {
			a := testAgent(t)
			n := &panelNDM{}
			a.ndmCommand = n.run
			switch mode {
			case "foreign-proxy":
				n.settings = []string{"domain static other.local"}
			case "foreign-dns":
				n.records = []string{"192.168.1.50"}
			case "custom-port":
				n.port = "8080"
			default:
				if err := a.ensurePanel(context.Background()); err != nil {
					t.Fatal(err)
				}
				if mode == "changed-proxy" {
					n.foreign = " security-level public\n"
				} else {
					n.records = []string{"192.168.1.50"}
				}
			}
			before := len(n.commands)
			var err error
			if strings.HasPrefix(mode, "changed") {
				err = a.cleanupPanel(context.Background())
			} else {
				err = a.ensurePanel(context.Background())
			}
			if err == nil || len(n.commands[before:]) != 1 {
				t.Fatalf("foreign config was modified: %v %v", err, n.commands[before:])
			}
		})
	}
}
func TestPanelNDMRollsBackPartialSetup(t *testing.T) {
	for _, failure := range []string{"ip http proxy " + panelProxy + " upstream http 192.168.1.1 8787", "system configuration save"} {
		t.Run(failure, func(t *testing.T) {
			a := testAgent(t)
			n := &panelNDM{fail: failure}
			a.ndmCommand = n.run
			if err := a.ensurePanel(context.Background()); err == nil {
				t.Fatal("failure ignored")
			}
			if n.settings != nil || len(n.records) > 0 {
				t.Fatal("partial setup remained")
			}
			if _, err := os.Stat(a.bindingPath()); !os.IsNotExist(err) {
				t.Fatal("marker remained after rollback")
			}
		})
	}
}
func TestPanelNDMPreservesExistingMatchingDNSAndSupportsOlderNDM(t *testing.T) {
	a := testAgent(t)
	n := &panelNDM{records: []string{a.cfg.LANIP}, noOrigin: true}
	a.ndmCommand = n.run
	if err := a.ensurePanel(context.Background()); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(a.bindingPath())
	var binding panelBinding
	_ = json.Unmarshal(data, &binding)
	if binding.OwnDNS {
		t.Fatal("claimed a preexisting record")
	}
	if err := a.cleanupPanel(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(n.records) != 1 {
		t.Fatal("deleted borrowed DNS")
	}
}
func TestPanelDNSIsLocalDuringVPNTunnel(t *testing.T) {
	a := testAgent(t)
	for _, kind := range []uint16{dns.TypeA, dns.TypeAAAA, dns.TypeTXT} {
		q := new(dns.Msg)
		q.SetQuestion(panelHost(a.cfg)+".", kind)
		w := &captureDNS{remote: "192.168.1.42"}
		a.answerDNS(w, q)
		if w.reply.Rcode != dns.RcodeSuccess {
			t.Fatal("local panel DNS failed")
		}
		if kind == dns.TypeA {
			if len(w.reply.Answer) != 1 || w.reply.Answer[0].(*dns.A).A.String() != a.cfg.LANIP {
				t.Fatal("panel DNS did not resolve to LAN")
			}
		} else if len(w.reply.Answer) != 0 {
			t.Fatal("unexpected panel DNS type")
		}
	}
}
