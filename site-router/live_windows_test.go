package main

import (
	"encoding/binary"
	"reflect"
	"testing"
)

func TestLiveSiteRuleChangesExistingFlowWithoutVPNReconnect(t *testing.T) {
	f := flow{Protocol: 6, Local: "10.0.0.2:50000", Remote: "9.9.9.9:443"}
	packet := make([]byte, 40)
	packet[0] = 0x45
	packet[9] = 6
	packet[33] = 0x10
	t1 := &routedTun{routes: map[flow]cachedRoute{}, fragments: map[fragmentKey]cachedRoute{}, owner: func(flow) string { return "chrome.exe" }}
	t1.policy.Store(newProcessPolicy(policyConfig{Whitelist: true}))
	if !t1.choose(f, packet) {
		t.Fatal("initial browser flow must be direct")
	}
	// Updating policy must invalidate the route of an existing connection.
	t1.updatePolicy(policyConfig{Whitelist: true, Targets: []string{"9.9.9.9/32"}})
	if t1.choose(f, packet) {
		t.Fatal("existing browser connection kept old direct route after adding site")
	}
}

func TestLiveUpdateClosesOnlyConnectionsWhoseRouteChanged(t *testing.T) {
	browser := flow{Protocol: 6, Local: "10.0.0.2:50000", Remote: "9.9.9.9:443"}
	app := flow{Protocol: 6, Local: "10.0.0.2:50001", Remote: "9.9.9.9:443"}
	otherSite := flow{Protocol: 6, Local: "10.0.0.2:50002", Remote: "8.8.8.8:443"}
	var closed []flow
	router := &routedTun{routes: map[flow]cachedRoute{}, fragments: map[fragmentKey]cachedRoute{}, owner: func(f flow) string {
		if f == app {
			return "game.exe"
		}
		return "chrome.exe"
	}, resetTCP: func(f flow) error { closed = append(closed, f); return nil }}
	router.policy.Store(newProcessPolicy(policyConfig{Whitelist: true}))
	packet := make([]byte, 40)
	packet[0] = 0x45
	packet[9] = 6
	packet[33] = 0x10
	router.choose(browser, packet)
	router.choose(app, packet)
	router.choose(otherSite, packet)
	if n := router.updatePolicy(policyConfig{Whitelist: true, Targets: []string{"9.9.9.9/32"}}); n != 1 {
		t.Fatalf("changed flows=%d", n)
	}
	if !reflect.DeepEqual(closed, []flow{browser}) {
		t.Fatalf("closed unrelated flows: %+v", closed)
	}
	if _, ok := router.routes[app]; !ok {
		t.Fatal("app connection was dropped")
	}
	if _, ok := router.routes[otherSite]; !ok {
		t.Fatal("other browser site was dropped")
	}
	if router.choose(browser, packet) {
		t.Fatal("selected browser site must now use VPN")
	}
	if n := router.updatePolicy(policyConfig{Whitelist: true}); n != 1 {
		t.Fatalf("deleting site changed %d flows", n)
	}
	if !router.choose(browser, packet) {
		t.Fatal("deleted site must become direct without reconnect")
	}
}

func TestDeleteTCPRowMatchesWindowsNetworkByteOrder(t *testing.T) {
	row, err := tcpDeleteRow(flow{Protocol: 6, Local: "10.66.0.2:50000", Remote: "8.8.8.8:443"})
	if err != nil {
		t.Fatal(err)
	}
	if binary.LittleEndian.Uint32(row[:4]) != 12 || string(row[4:8]) != string([]byte{10, 66, 0, 2}) || binary.BigEndian.Uint16(row[8:10]) != 50000 || binary.BigEndian.Uint16(row[16:18]) != 443 {
		t.Fatal("wrong DELETE_TCB row encoding")
	}
}

func TestLiveAppExclusionChangesExistingFlowWithoutVPNReconnect(t *testing.T) {
	f := flow{Protocol: 17, Local: "10.0.0.2:50000", Remote: "9.9.9.9:443"}
	packet := make([]byte, 28)
	packet[0] = 0x45
	packet[9] = 17
	binary.BigEndian.PutUint16(packet[2:4], 28)
	t1 := &routedTun{routes: map[flow]cachedRoute{}, fragments: map[fragmentKey]cachedRoute{}, owner: func(flow) string { return "game.exe" }}
	t1.policy.Store(newProcessPolicy(policyConfig{}))
	if t1.choose(f, packet) {
		t.Fatal("initial app must use VPN")
	}
	t1.updatePolicy(policyConfig{Excluded: []string{"game.exe"}})
	if !t1.choose(f, packet) {
		t.Fatal("existing app connection ignored new exclusion")
	}
}
