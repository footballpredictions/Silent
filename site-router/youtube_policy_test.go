package main

import (
	"encoding/json"
	"net/netip"
	"os/exec"
	"testing"
)

// Exercise the exact JSON produced by Electron, not a hand-written expansion
// that could diverge from the browser's real startup/live policy.
func TestYouTubeElectronPolicyLearnsResourceDNSWithoutChangingApps(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node is required for the Electron policy integration")
	}
	for _, whitelist := range []bool{true, false} {
		mode := "false"
		if whitelist {
			mode = "true"
		}
		output, err := exec.Command(node, "-e", `const s=require('../src/main/apps/siteBypass'); console.log(JSON.stringify(s.initialBrowserPolicy(['youtube.com'],`+mode+`)))`).Output()
		if err != nil {
			t.Fatal(err)
		}
		var config policyConfig
		if err := json.Unmarshal(output, &config); err != nil {
			t.Fatal(err)
		}
		// Snapshot has completed; subsequent dynamic CDN answers arrive in TUN.
		config.PendingDNS = false
		config.Excluded = []string{"msedge.exe"}
		p := newProcessPolicy(config)
		for i, host := range []string{"yt3.ggpht.com", "i.ytimg.com", "rr4---sn-qjp5q5-5h.googlevideo.com"} {
			ip := netip.AddrFrom4([4]byte{192, 0, 2, byte(10 + i)})
			p.sites.observeDNS(answerPacket(t, host, ip.As4(), 60))
			if p.direct("chrome.exe", ip, 443) == whitelist {
				t.Fatalf("YouTube resource %s used the wrong route (whitelist=%v)", host, whitelist)
			}
			if p.direct("game.exe", ip, 443) || !p.direct("msedge.exe", ip, 443) {
				t.Fatal("YouTube site rule changed ordinary/excluded application routing")
			}
			removed := updatedProcessPolicy(p, policyConfig{Whitelist: whitelist, Domains: []string{"other.example"}})
			if removed.direct("chrome.exe", ip, 443) != whitelist {
				t.Fatal("deleted YouTube rule retained a learned resource address")
			}
		}
		if p.direct("chrome.exe", netip.MustParseAddr("198.51.100.1"), 443) != whitelist {
			t.Fatal("YouTube rule changed an unrelated browser destination")
		}
	}
}
