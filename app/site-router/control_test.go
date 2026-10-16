package main

import (
	"bytes"
	"net/netip"
	"strings"
	"testing"
	"time"
)

func TestTargetUpdatePreservesLearnedDNSAndApplicationPolicy(t *testing.T) {
	p := newPolicy(false, []string{"203.0.113.1"}, []int{10001})
	learned := netip.MustParseAddr("198.51.100.8")
	p.learned[learned] = time.Now().Add(time.Minute)
	var output bytes.Buffer
	if err := applyTargetUpdates(strings.NewReader("{\"revision\":7,\"targets\":[\"203.0.113.2\"]}\n"), p, &output); err != nil {
		t.Fatal(err)
	}
	if output.String() != "POLICY_READY:7\n" {
		t.Fatal(output.String())
	}
	if !p.direct(10001, netip.MustParseAddr("203.0.113.2")) || p.direct(10001, netip.MustParseAddr("203.0.113.1")) {
		t.Fatal("Rotated target addresses were not applied")
	}
	if !p.direct(10001, learned) || p.direct(10002, learned) {
		t.Fatal("Live DNS/app policy was lost")
	}
}

func TestNetworkUpdateKeepsManualTargetsAndDeduplicatesEpoch(t *testing.T) {
	p := newPolicy(false, []string{"203.0.113.1"}, []int{10001})
	var output bytes.Buffer
	resets := 0
	input := "{\"revision\":1,\"network_epoch\":9}\n{\"revision\":2,\"network_epoch\":9}\n{\"revision\":3,\"network_epoch\":8}\n"
	if err := applyRouterUpdates(strings.NewReader(input), p, &output, nil, func() { resets++ }); err != nil {
		t.Fatal(err)
	}
	if resets != 1 || !p.direct(10001, netip.MustParseAddr("203.0.113.1")) {
		t.Fatal("Network update lost targets or repeated a completed handover")
	}
}
