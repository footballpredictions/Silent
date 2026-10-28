// Package routerpolicy is shared by the Keenetic resolver and OpenWrt DNS adapter.
package routerpolicy

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"net"
	"strings"
)

const MaxSize = 262144
const Catalog = "catalog-test"

type Route int

const (
	Default Route = iota
	Direct
	VPN
)

type Policy struct {
	Schema   int      `json:"schema_version"`
	Profile  string   `json:"profile,omitempty"`
	Revision string   `json:"revision"`
	Direct   []string `json:"direct_domains"`
	Exact    []string `json:"direct_exact_domains,omitempty"`
	VPN      []string `json:"vpn_domains"`
}

func ValidDomain(s string) bool {
	if len(s) == 0 || len(s) > 253 || net.ParseIP(s) != nil {
		return false
	}
	for _, label := range strings.Split(s, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
				return false
			}
		}
	}
	return strings.Contains(s, ".") || s == "ru" || s == "su" || s == "xn--p1ai"
}
func Parse(raw []byte) (Policy, error) {
	var p Policy
	if len(raw) > MaxSize || json.Unmarshal(raw, &p) != nil {
		return p, errors.New("invalid routing policy")
	}
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(raw, &fields)
	if exact, present := fields["direct_exact_domains"]; present && !strings.HasPrefix(strings.TrimSpace(string(exact)), "[") {
		return p, errors.New("exact domains must be an array")
	}
	hash, err := hex.DecodeString(p.Revision)
	if p.Schema != 1 || err != nil || len(hash) != 32 || p.Revision != strings.ToLower(p.Revision) || p.Direct == nil || p.VPN == nil || (p.Profile != "" && p.Profile != Catalog) {
		return p, errors.New("invalid routing policy")
	}
	for _, list := range [][]string{p.Direct, p.Exact, p.VPN} {
		if len(list) > 2000 {
			return p, errors.New("too many routing rules")
		}
		for _, d := range list {
			if !ValidDomain(d) {
				return p, errors.New("invalid routing domain")
			}
		}
	}
	return p, nil
}
func Suffix(name string, domains []string) bool {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	for _, d := range domains {
		if name == d || strings.HasSuffix(name, "."+d) {
			return true
		}
	}
	return false
}
func (p Policy) Match(name string) Route {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	if Suffix(name, p.VPN) {
		return VPN
	}
	if Suffix(name, p.Direct) {
		return Direct
	}
	for _, exact := range p.Exact {
		if name == exact {
			return Direct
		}
	}
	return Default
}
