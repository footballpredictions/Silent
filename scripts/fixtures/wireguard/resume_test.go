package main

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"golang.org/x/crypto/curve25519"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/tuntest"
	"net/netip"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type observedBind struct {
	conn.Bind
	port  atomic.Uint32
	opens atomic.Uint32
}

func (b *observedBind) Open(port uint16) ([]conn.ReceiveFunc, uint16, error) {
	f, p, e := b.Bind.Open(port)
	if e == nil {
		b.port.Store(uint32(p))
		b.opens.Add(1)
	}
	return f, p, e
}

func TestWakeRestoresWireGuardUDPWithoutReplacingTheDevice(t *testing.T) {
	testWireGuardWake(t, false)
}

func TestWakeRestoresDataWhenServerForgotTheOldTransportKeys(t *testing.T) {
	testWireGuardWake(t, true)
}

func testWireGuardWake(t *testing.T, serverForgot bool) {
	var keys [2][32]byte
	var public [2][]byte
	var devices [2]*device.Device
	var tunnels [2]*tuntest.ChannelTUN
	var binds [2]*observedBind
	for i := 0; i < 2; i++ {
		for j := range keys[i] {
			keys[i][j] = byte(j + 1 + 40*i)
		}
		public[i], _ = curve25519.X25519(keys[i][:], curve25519.Basepoint)
	}
	for i := 0; i < 2; i++ {
		tunnels[i] = tuntest.NewChannelTUN()
		binds[i] = &observedBind{Bind: conn.NewStdNetBind()}
		devices[i] = device.NewDevice(tunnels[i].TUN(), binds[i], device.NewLogger(device.LogLevelSilent, ""))
		defer devices[i].Close()
		cfg := fmt.Sprintf("private_key=%s\nlisten_port=0\npublic_key=%s\nallowed_ip=10.99.0.%d/32\n", hex.EncodeToString(keys[i][:]), hex.EncodeToString(public[1-i]), 2-i)
		if e := devices[i].IpcSet(cfg); e != nil {
			t.Fatal(e)
		}
		if e := devices[i].Up(); e != nil {
			t.Fatal(e)
		}
	}
	for i := 0; i < 2; i++ {
		cfg := fmt.Sprintf("public_key=%s\nendpoint=127.0.0.1:%d\n", hex.EncodeToString(public[1-i]), binds[1-i].port.Load())
		if e := devices[i].IpcSet(cfg); e != nil {
			t.Fatal(e)
		}
	}
	send := func(from, to int) {
		t.Helper()
		packet := tuntest.Ping(netip.MustParseAddr(fmt.Sprintf("10.99.0.%d", to+1)), netip.MustParseAddr(fmt.Sprintf("10.99.0.%d", from+1)))
		select {
		case tunnels[from].Outbound <- packet:
		case <-time.After(time.Second):
			t.Fatal("TUN input stuck")
		}
		select {
		case received := <-tunnels[to].Inbound:
			if !bytes.Equal(packet, received) {
				t.Fatal("wrong decrypted packet")
			}
		case <-time.After(2 * time.Second):
			t.Fatal("WireGuard data path did not recover")
		}
	}
	send(0, 1)
	send(1, 0)
	before, _ := devices[0].IpcGet()
	time.Sleep(50 * time.Millisecond) // A wake is beyond WG's handshake rate limit.
	if serverForgot {
		// The phone can retain its transport key while the server expires it
		// during suspension. TURN/STUN renewal cannot repair this WG state.
		var clientPublic device.NoisePublicKey
		copy(clientPublic[:], public[0])
		devices[1].LookupPeer(clientPublic).ZeroAndFlushAll()
	}
	opens := binds[0].opens.Load()
	// Simulate the UDP socket being invalidated while the VPN device remains up.
	if e := binds[0].Close(); e != nil {
		t.Fatal(e)
	}
	engineDev = devices[0]
	defer func() { engineDev = nil }()
	wdtt_network_event(0)
	deadline := time.Now().Add(time.Second)
	for binds[0].opens.Load() == opens && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if binds[0].opens.Load() == opens {
		t.Fatal("wake left the WireGuard UDP transport closed while the VPN still looked active")
	}
	send(0, 1)
	send(1, 0)
	after, _ := devices[0].IpcGet()
	for _, line := range strings.Split(before, "\n") {
		if strings.HasPrefix(line, "private_key=") && !strings.Contains(after, line) {
			t.Fatal("wake replaced WireGuard keys")
		}
	}
}
