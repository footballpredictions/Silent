package main

import (
	"context"
	"crypto/subtle"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed web
var assets embed.FS

type Agent struct {
	mu                sync.RWMutex
	op                sync.Mutex
	saveMu            sync.Mutex
	updateMu          sync.RWMutex
	cfg               Config
	path, root, model string
	client            *http.Client
	bases             []string
	connected         bool
	cancel            context.CancelFunc
	stopTunnel        func()
	domains           []string
	vpnDomains        []string
	policyMu          sync.RWMutex
	learnedMu         sync.Mutex
	policyRevision    string
	lastPolicy        time.Time
	learnedDirect     map[string]bool
	learnedVPN        map[string]bool
	pathReady         func() bool
	upstream          []string
	wgAddress         string
	servers           []*dnsServer
	run               func(context.Context, string, ...string) error
	restoreSets       func(context.Context, string) error
}

func (a *Agent) persist() error {
	a.saveMu.Lock()
	defer a.saveMu.Unlock()
	a.mu.RLock()
	c := a.cfg
	a.mu.RUnlock()
	return saveConfig(a.path, c)
}
func (a *Agent) isConnected() bool { a.mu.RLock(); defer a.mu.RUnlock(); return a.connected }
func (a *Agent) lanURL() string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return fmt.Sprintf("http://%s:%d", a.cfg.LANIP, a.cfg.Port)
}
func (a *Agent) status() any {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return map[string]any{"version": version, "platform": "keenetic", "arch": packageArch, "build_id": packageBuildID, "device_id": a.cfg.DeviceID, "lan_ip": a.cfg.LANIP, "lan_url": fmt.Sprintf("http://%s:%d", a.cfg.LANIP, a.cfg.Port), "router_name": "Keenetic " + a.model, "connected": a.connected, "session": a.cfg.Token != "", "cloak": true, "ru_direct": a.cfg.Direct, "dns_preset": a.cfg.DNSPreset, "dns_custom": a.cfg.DNSCustom, "email": a.cfg.Email}
}
func reply(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func (a *Agent) handler() http.Handler {
	webFS, _ := fs.Sub(assets, "web")
	files := http.FileServer(http.FS(webFS))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		a.mu.RLock()
		cfg := a.cfg
		a.mu.RUnlock()
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		// Bind + subnet + Host checks also prevent DNS rebinding to the LAN admin.
		host := r.Host
		if h, _, err := net.SplitHostPort(host); err == nil {
			host = h
		}
		remote, _, _ := net.SplitHostPort(r.RemoteAddr)
		_, subnet, _ := net.ParseCIDR(cfg.LANPrefix)
		if host != cfg.LANIP || !subnet.Contains(net.ParseIP(remote)) {
			http.Error(w, "LAN only", 403)
			return
		}
		user, pass, ok := r.BasicAuth()
		if !ok || user != "admin" || subtle.ConstantTimeCompare([]byte(pass), []byte(cfg.AdminPassword)) != 1 {
			w.Header().Set("WWW-Authenticate", `Basic realm="Silent Keenetic", charset="UTF-8"`)
			http.Error(w, "Нужен пароль локальной панели", 401)
			return
		}
		if r.Method != "GET" && r.Method != "HEAD" {
			if origin := r.Header.Get("Origin"); origin != "" && origin != a.lanURL() {
				http.Error(w, "Invalid origin", 403)
				return
			}
			if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
				http.Error(w, "Invalid origin", 403)
				return
			}
			if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
				http.Error(w, "JSON required", 415)
				return
			}
		}
		if strings.HasPrefix(r.URL.Path, "/cgi-bin/silent-api/") {
			a.serveAPI(w, r)
			return
		}
		if r.Method != "GET" && r.Method != "HEAD" {
			http.Error(w, "Method", 405)
			return
		}
		if r.URL.Path != "/" {
			r.URL.Path = strings.TrimPrefix(r.URL.Path, "/silent-vpn")
		}
		files.ServeHTTP(w, r)
	})
}

func (a *Agent) serveAPI(w http.ResponseWriter, r *http.Request) {
	op := strings.TrimPrefix(r.URL.Path, "/cgi-bin/silent-api/")
	methods := map[string]string{"status": "GET", "theme": "GET", "login": "POST", "register": "POST", "forgot": "POST", "profile": "GET", "referral": "GET", "servers": "GET", "server": "POST", "pay": "POST", "pay-preview": "POST", "pay-status": "POST", "promo": "POST", "connect": "POST", "disconnect": "POST", "logout": "POST", "log": "GET", "update-check": "GET", "update-status": "GET", "update-start": "POST"}
	method, exists := methods[op]
	if op == "device-rename" || op == "device-delete" {
		method, exists = "POST", true
	}
	if op == "dns" || op == "exclusions" {
		exists = true
		method = r.Method
		if method != "GET" && method != "POST" {
			method = "GET"
		}
	}
	if !exists {
		reply(w, 404, map[string]string{"detail": "unknown op"})
		return
	}
	if method != r.Method {
		reply(w, 405, map[string]string{"detail": "Method not allowed"})
		return
	}
	body := map[string]any{}
	if r.Method == "POST" {
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 65536)).Decode(&body); err != nil {
			reply(w, 400, map[string]string{"detail": "Некорректный JSON"})
			return
		}
	}
	ctx := r.Context()
	if r.Method == "POST" {
		if op == "update-start" {
			a.updateMu.Lock()
			defer a.updateMu.Unlock()
		} else {
			a.updateMu.RLock()
			defer a.updateMu.RUnlock()
		}
	}
	if updateBusy(a.path) && (op == "login" || op == "connect" || op == "disconnect" || op == "logout" || op == "server" || op == "device-rename" || op == "device-delete" || ((op == "dns" || op == "exclusions") && r.Method == "POST")) {
		reply(w, http.StatusConflict, map[string]string{"detail": "Дождитесь завершения обновления"})
		return
	}
	var v any
	var err error
	switch op {
	case "device-rename", "device-delete":
		id, _ := body["id"].(string)
		if len(id) == 0 || len(id) > 128 || strings.Trim(id, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != "" {
			reply(w, 400, map[string]string{"detail": "Некорректная сессия"})
			return
		}
		a.mu.RLock()
		token := a.cfg.Token
		a.mu.RUnlock()
		if token == "" {
			reply(w, 401, map[string]string{"detail": "Войдите в аккаунт"})
			return
		}
		if op == "device-rename" {
			name, _ := body["name"].(string)
			name = strings.TrimSpace(name)
			if len([]rune(name)) == 0 || len([]rune(name)) > 64 {
				reply(w, 400, map[string]string{"detail": "Имя должно содержать от 1 до 64 символов"})
				return
			}
			v, err = a.callSession(ctx, "PATCH", "/api/users/devices/"+id, map[string]string{"device_name": name})
		} else {
			v, err = a.callSession(ctx, "DELETE", "/api/users/devices/"+id, nil)
		}
	case "update-check":
		v = a.checkUpdate(ctx)
	case "update-status":
		v = updateStatus(a.path)
	case "update-start":
		v, err = a.startUpdate()
	case "status":
		v = a.status()
	case "log":
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte("Лог отключён"))
		return
	case "login":
		v, err = a.login(ctx, body)
	case "connect":
		err = a.connect(ctx)
		v = map[string]bool{"ok": true, "connected": a.isConnected()}
	case "disconnect":
		a.interrupt()
		a.op.Lock()
		err = a.disconnect()
		a.op.Unlock()
		v = map[string]bool{"ok": true, "connected": false}
	case "logout":
		// Panel sign-out must not tear down a VPN used by the rest of the LAN.
		a.op.Lock()
		a.mu.Lock()
		a.cfg.Token, a.cfg.RefreshToken, a.cfg.Email = "", "", ""
		a.mu.Unlock()
		err = a.persist()
		a.op.Unlock()
		v = map[string]bool{"ok": true, "connected": a.isConnected()}
	case "dns", "exclusions":
		a.op.Lock()
		if r.Method == "POST" {
			if a.isConnected() {
				err = fmt.Errorf("Отключите VPN перед изменением настроек")
			} else {
				a.mu.Lock()
				old := a.cfg
				if op == "dns" {
					preset, _ := body["preset"].(string)
					custom, _ := body["custom"].(string)
					a.cfg.DNSPreset, a.cfg.DNSCustom = preset, custom
				} else {
					enabled, ok := body["ru_direct"].(bool)
					if !ok {
						err = fmt.Errorf("ru_direct: нужен boolean")
					} else {
						a.cfg.Direct = enabled
					}
				}
				if err == nil {
					err = a.cfg.validate()
				}
				if err != nil {
					a.cfg = old
				}
				a.mu.Unlock()
				if err == nil {
					err = a.persist()
				}
			}
		}
		a.mu.RLock()
		if op == "dns" {
			v = map[string]any{"preset": a.cfg.DNSPreset, "custom": a.cfg.DNSCustom}
		} else {
			v = map[string]bool{"ru_direct": a.cfg.Direct}
		}
		a.mu.RUnlock()
		a.op.Unlock()
	default:
		paths := map[string]string{"theme": "/api/vpn/theme", "register": "/api/auth/register", "forgot": "/api/auth/forgot-password", "profile": "/api/users/me", "referral": "/api/users/me/referral", "promo": "/api/payments/promo/check", "servers": "/api/vpn/servers?fingerprint=" + a.fpQuery() + "&app_version=" + version, "pay": "/api/payments/init", "pay-preview": "/api/payments/preview", "server": "/api/vpn/servers/select"}
		path := paths[op]
		var payload any
		if r.Method == "POST" {
			payload = body
		}
		if op == "server" {
			if a.isConnected() {
				err = fmt.Errorf("Отключите VPN перед сменой сервера")
				break
			}
			a.op.Lock()
			defer a.op.Unlock()
			if a.isConnected() {
				err = fmt.Errorf("Отключите VPN перед сменой сервера")
				break
			}
			key, _ := body["key"].(string)
			payload = map[string]string{"device_fingerprint": a.cfg.Fingerprint, "preferred_server": key, "app_version": version}
			_, err = a.call(ctx, "POST", "/api/vpn/device/register", a.deviceBody())
			if err != nil {
				break
			}
		}
		if op == "pay-status" {
			label, _ := body["label"].(string)
			if !validLabel(label) {
				err = fmt.Errorf("Некорректный платёж")
				break
			}
			path = "/api/payments/status/" + label
			method = "GET"
			payload = nil
		}
		if op == "profile" {
			v, err = a.callSession(ctx, method, path, payload)
		} else {
			v, err = a.call(ctx, method, path, payload)
		}
	}
	if err != nil {
		var ae *apiError
		if errors.As(err, &ae) {
			reply(w, ae.Code, ae.Body)
		} else {
			reply(w, 502, map[string]string{"detail": err.Error()})
		}
		return
	}
	reply(w, 200, v)
}

func validLabel(s string) bool {
	if !strings.HasPrefix(s, "silent_") || len(s) > 100 || len(s) < 8 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_') {
			return false
		}
	}
	return true
}

func main() {
	path := flag.String("config", "/opt/etc/silent-keenetic/config.json", "config")
	root := flag.String("root", "/opt/lib/silent-keenetic", "runtime files")
	initLAN := flag.String("init-lan", "", "initialize LAN interface")
	lanIP := flag.String("lan-ip", "", "LAN IPv4")
	lanPrefix := flag.String("lan-prefix", "", "LAN prefix")
	check := flag.Bool("check", false, "check prerequisites without changing routes")
	cleanup := flag.Bool("cleanup", false, "remove only Silent Keenetic network state")
	restore := flag.String("restore", "", "restore own netfilter table")
	updateWorker := flag.Bool("update-worker", false, "run detached Keenetic update")
	updateCheck := flag.Bool("update-busy-check", false, "refuse manual uninstall while update runs")
	flag.Parse()
	if *updateCheck {
		if updateBusy(*path) {
			fmt.Fprintln(os.Stderr, "Дождитесь завершения обновления")
			os.Exit(1)
		}
		return
	}
	if *updateWorker {
		if err := runUpdateWorker(*path, *root); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *initLAN != "" {
		if _, err := os.Stat(*path); err == nil {
			fmt.Fprintln(os.Stderr, "Конфигурация уже существует")
			os.Exit(1)
		}
		c := Config{LANInterface: *initLAN, LANIP: *lanIP, LANPrefix: *lanPrefix, Port: 8787, AdminPassword: randomID(), Fingerprint: randomID(), DNSPreset: "server"}
		if err := c.validate(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := saveConfig(*path, c); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Printf("Панель: http://%s:%d\nЛогин: admin\nПароль: %s\n", c.LANIP, c.Port, c.AdminPassword)
		return
	}
	c, err := loadConfig(*path)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	model, _ := os.Hostname()
	a := &Agent{cfg: c, path: *path, root: *root, model: model, client: newHTTPClient(), bases: publicAPIs, run: runCommand}
	if !*check && *restore == "" {
		unlock, err := processLock(filepath.Join(filepath.Dir(*path), "agent.lock"))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer unlock()
	}
	if *cleanup {
		if err = a.network(context.Background(), "down"); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *restore != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err = a.network(ctx, "restore", *restore); err != nil {
			os.Exit(1)
		}
		return
	}
	if *check {
		if err = a.network(context.Background(), "check"); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("Prerequisites OK")
		return
	}
	if err = a.network(context.Background(), "check"); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err = a.network(context.Background(), "down"); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	a.loadPolicy()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	server := &http.Server{Addr: net.JoinHostPort(c.LANIP, fmt.Sprint(c.Port)), Handler: a.handler(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16384}
	listener, err := net.Listen("tcp", server.Addr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	readyFile := filepath.Join(filepath.Dir(a.path), "web.ready")
	if err = os.WriteFile(readyFile, []byte(fmt.Sprint(os.Getpid())), 0600); err != nil {
		listener.Close()
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer os.Remove(readyFile)
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		<-ctx.Done()
		a.interrupt()
		a.op.Lock()
		a.mu.RLock()
		reconnect := a.cfg.Reconnect
		a.mu.RUnlock()
		a.disconnect()
		a.mu.Lock()
		a.cfg.Reconnect = reconnect
		a.mu.Unlock()
		_ = a.persist()
		a.op.Unlock()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	go a.watch(ctx)
	if c.Reconnect && c.Token != "" {
		go func() {
			for updateBusy(a.path) {
				select {
				case <-ctx.Done():
					return
				case <-time.After(time.Second):
				}
			}
			_ = a.connect(ctx)
		}()
	}
	if err = server.Serve(listener); err != nil && err != http.ErrServerClosed {
		stop()
		fmt.Fprintln(os.Stderr, err)
	}
	<-finished
}
