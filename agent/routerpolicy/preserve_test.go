package routerpolicy

import "testing"

func TestPreservesLearnedRequiresUnchangedMeaningForOldRoutes(t *testing.T) {
	base := Policy{Schema: 1, Direct: []string{"service.ru"}, Exact: []string{"exact.test", "special.force.ru"}, VPN: []string{"force.ru"}}
	tests := []struct {
		name string
		next Policy
		want bool
	}{
		{"same", base, true},
		{"add direct", Policy{Schema: 1, Direct: []string{"service.ru", "new.ru"}, Exact: base.Exact, VPN: base.VPN}, true},
		{"broaden direct", Policy{Schema: 1, Direct: []string{"ru"}, Exact: base.Exact, VPN: base.VPN}, true},
		{"exact becomes suffix", Policy{Schema: 1, Direct: []string{"service.ru", "exact.test"}, Exact: []string{"special.force.ru"}, VPN: base.VPN}, true},
		{"remove direct", Policy{Schema: 1, Direct: []string{}, Exact: base.Exact, VPN: base.VPN}, false},
		{"suffix becomes exact", Policy{Schema: 1, Direct: []string{}, Exact: append([]string{"service.ru"}, base.Exact...), VPN: base.VPN}, false},
		{"remove exact", Policy{Schema: 1, Direct: base.Direct, VPN: base.VPN}, false},
		{"add forced VPN", Policy{Schema: 1, Direct: base.Direct, Exact: base.Exact, VPN: []string{"force.ru", "private.service.ru"}}, false},
		{"remove forced VPN", Policy{Schema: 1, Direct: base.Direct, Exact: base.Exact, VPN: []string{}}, false},
		{"missing VPN", Policy{Schema: 1, Direct: base.Direct, Exact: base.Exact}, false},
		{"invalid schema", Policy{Schema: 2, Direct: base.Direct, Exact: base.Exact, VPN: base.VPN}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := PreservesLearned(base, tt.next); got != tt.want {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
		})
	}
}
