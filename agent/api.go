package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

var publicAPIs = []string{"http://87.58.213.193:9100", "http://78.17.74.27:9100", "https://89-125-188-100.nip.io", "https://89.125.188.100"}

type apiError struct {
	Code int
	Body json.RawMessage
}

func (e *apiError) Error() string {
	var v struct {
		Detail any `json:"detail"`
	}
	if json.Unmarshal(e.Body, &v) == nil && v.Detail != nil {
		return fmt.Sprint(v.Detail)
	}
	return fmt.Sprintf("Сервер ответил %d", e.Code)
}

func (a *Agent) call(ctx context.Context, method, path string, body any) (json.RawMessage, error) {
	a.mu.RLock()
	token, connected := a.cfg.Token, a.connected
	a.mu.RUnlock()
	bases := a.bases
	if connected {
		bases = []string{tunnelAPI}
	}
	var payload []byte
	if body != nil {
		var err error
		payload, err = json.Marshal(body)
		if err != nil {
			return nil, err
		}
	}
	for _, base := range bases {
		req, err := http.NewRequestWithContext(ctx, method, base+path, bytes.NewReader(payload))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-App-Version", version)
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		res, err := a.client.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			continue
		}
		b, readErr := io.ReadAll(io.LimitReader(res.Body, 2<<20))
		res.Body.Close()
		if readErr != nil || !json.Valid(b) {
			continue
		}
		// Access/subscription failures are authoritative; never fail over to bypass them.
		if res.StatusCode >= 400 && res.StatusCode < 500 {
			return nil, &apiError{res.StatusCode, b}
		}
		if res.StatusCode >= 500 {
			continue
		}
		return b, nil
	}
	return nil, fmt.Errorf("Сервер недоступен. Повторите попытку")
}

func (a *Agent) deviceBody() map[string]string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return map[string]string{"device_fingerprint": a.cfg.Fingerprint, "device_type": "pc", "device_name": "Keenetic " + a.model, "bootstrap_hash": bootstrapHash}
}
func (a *Agent) fpQuery() string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return url.QueryEscape(a.cfg.Fingerprint)
}

func (a *Agent) login(ctx context.Context, body map[string]any) (any, error) {
	a.op.Lock()
	defer a.op.Unlock()
	if a.isConnected() {
		return nil, fmt.Errorf("Сначала отключите VPN")
	}
	committed := false
	defer func() {
		if !committed {
			a.mu.Lock()
			a.cfg.Token, a.cfg.RefreshToken, a.cfg.Email = "", "", ""
			a.mu.Unlock()
			_ = a.persist()
		}
	}()
	raw, err := a.call(ctx, "POST", "/api/auth/login", body)
	if err != nil {
		return nil, err
	}
	var v struct {
		Access  string `json:"access_token"`
		Refresh string `json:"refresh_token"`
	}
	if json.Unmarshal(raw, &v) != nil || len(strings.Split(v.Access, ".")) != 3 {
		return nil, fmt.Errorf("Сервер не вернул сессию")
	}
	a.mu.Lock()
	a.cfg.Token, a.cfg.RefreshToken = v.Access, v.Refresh
	a.mu.Unlock()
	profile, err := a.call(ctx, "GET", "/api/users/me", nil)
	if err != nil {
		a.mu.Lock()
		a.cfg.Token, a.cfg.RefreshToken, a.cfg.Email = "", "", ""
		a.mu.Unlock()
		_ = a.persist()
		return nil, err
	}
	var p struct {
		Email string `json:"email"`
	}
	if json.Unmarshal(profile, &p) != nil || p.Email == "" {
		return nil, fmt.Errorf("Сервер не вернул аккаунт")
	}
	a.mu.Lock()
	a.cfg.Email = p.Email
	a.mu.Unlock()
	if err = a.persist(); err != nil {
		return nil, err
	}
	committed = true
	_, _ = a.call(ctx, "POST", "/api/vpn/device/register", a.deviceBody())
	return map[string]any{"email": p.Email, "profile": profile, "lan_ip": a.cfg.LANIP, "lan_url": a.lanURL(), "router_name": "Keenetic " + a.model, "connected": false}, nil
}

func (a *Agent) refresh(ctx context.Context) {
	a.mu.RLock()
	token := a.cfg.RefreshToken
	a.mu.RUnlock()
	if token == "" {
		return
	}
	raw, err := a.call(ctx, "POST", "/api/auth/refresh", map[string]string{"refresh_token": token})
	if err != nil {
		return
	}
	var v struct {
		Access  string `json:"access_token"`
		Refresh string `json:"refresh_token"`
	}
	if json.Unmarshal(raw, &v) == nil && v.Access != "" {
		a.mu.Lock()
		a.cfg.Token = v.Access
		if v.Refresh != "" {
			a.cfg.RefreshToken = v.Refresh
		}
		a.mu.Unlock()
		_ = a.persist()
	}
}

func newHTTPClient() *http.Client {
	return &http.Client{Timeout: 8 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
}
