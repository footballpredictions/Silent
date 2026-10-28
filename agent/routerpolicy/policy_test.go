package routerpolicy

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestTypedRulesAndVPNPrecedence(t *testing.T) {
	p := Policy{Direct: []string{"service.ru"}, Exact: []string{"exact.net", "special.blocked.ru"}, VPN: []string{"blocked.ru", "force.service.ru"}}
	for name, want := range map[string]Route{"service.ru": Direct, "child.service.ru": Direct, "EXACT.NET.": Direct, "child.exact.net": Default, "special.blocked.ru": VPN, "force.service.ru": VPN, "notservice.ru": Default, "else.net": Default} {
		if got := p.Match(name); got != want {
			t.Errorf("%s: %v want %v", name, got, want)
		}
	}
}
func TestOptionalExactRulesAndLegacyPolicy(t *testing.T) {
	p := Policy{Schema: 1, Revision: strings.Repeat("a", 64), Direct: []string{}, VPN: []string{}}
	raw, _ := json.Marshal(p)
	if _, err := Parse(raw); err != nil {
		t.Fatal(err)
	}
	p.Profile = Catalog
	p.Exact = []string{"exact.ru"}
	raw, _ = json.Marshal(p)
	got, err := Parse(raw)
	if err != nil || got.Match("exact.ru") != Direct {
		t.Fatal("exact catalog lost", err)
	}
	for _, invalid := range []string{"*.ru", "A.ru", "bad;echo.ru", "1.1.1.1", ".ru"} {
		p.Exact = []string{invalid}
		raw, _ = json.Marshal(p)
		if _, err := Parse(raw); err == nil {
			t.Error("accepted", invalid)
		}
	}
}
