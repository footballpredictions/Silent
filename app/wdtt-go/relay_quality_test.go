package main

import (
	"context"
	"errors"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/pion/stun/v3"
	"github.com/pion/turn/v5"
)

func qualityWorkers() []*WorkerSlot {
	return []*WorkerSlot{{ID: 0, quality: &relayQuality{}}, {ID: 1, quality: &relayQuality{}}, {ID: 2, quality: &relayQuality{}}}
}

func probeRound(ws []*WorkerSlot, scheduler *relayScheduler, now time.Time, delay []time.Duration, failed int) {
	for i, w := range ws {
		var err error
		if i == failed {
			err = errors.New("fixture binding timeout")
		}
		w.quality.observe(delay[i], err, now)
	}
	scheduler.refresh(ws, now)
}

func TestRelayQualityNeedsRepeatedEvidenceAndRecovers(t *testing.T) {
	now := time.Unix(1000, 0)
	ws, s := qualityWorkers(), &relayScheduler{}
	for i := 0; i < 5; i++ {
		probeRound(ws, s, now.Add(time.Duration(i)*10*time.Second), []time.Duration{20 * time.Millisecond, 25 * time.Millisecond, 600 * time.Millisecond}, -1)
		if s.states[ws[2]].penalized != (i >= 4) {
			t.Fatalf("probe %d: insufficient evidence or slow path not downweighted", i)
		}
	}
	counts := make([]int, len(ws))
	for i := 0; i < 90; i++ {
		counts[s.next(ws, 0, now.Add(41*time.Second))]++
	}
	if counts[0] != 40 || counts[1] != 40 || counts[2] != 10 {
		t.Fatalf("healthy paths need more traffic without starving poor path: %v", counts)
	}
	for i := 5; i < 24; i++ {
		probeRound(ws, s, now.Add(time.Duration(i)*10*time.Second), []time.Duration{20 * time.Millisecond, 25 * time.Millisecond, 22 * time.Millisecond}, -1)
	}
	if s.states[ws[2]].penalized {
		t.Fatal("recovered relay remained penalized")
	}
}

func TestRelayQualityNeverConfusesOneTimeoutOrIdleWithPersistentFailure(t *testing.T) {
	now := time.Unix(1000, 0)
	ws, s := qualityWorkers(), &relayScheduler{}
	delays := []time.Duration{20 * time.Millisecond, 20 * time.Millisecond, 20 * time.Millisecond}
	probeRound(ws, s, now, delays, 2)
	for i := 1; i < 4; i++ {
		s.refresh(ws, now.Add(time.Duration(i)*time.Second))
	}
	if s.states[ws[2]].penalized {
		t.Fatal("one timeout was counted several times")
	}
	probeRound(ws, s, now.Add(10*time.Second), delays, 2)
	if s.states[ws[2]].penalized {
		t.Fatal("two timeouts must not downweight an established relay")
	}
	probeRound(ws, s, now.Add(20*time.Second), delays, 2)
	if !s.states[ws[2]].penalized {
		t.Fatal("three independent failures not detected")
	}
	s.refresh(ws, now.Add(66*time.Second))
	if s.states[ws[2]].penalized {
		t.Fatal("stale observations must restore equal fallback")
	}
}

func TestRelayQualityEqualAndMissingSamplesPreserveRoundRobin(t *testing.T) {
	for _, sampled := range []bool{false, true} {
		ws, s, now := qualityWorkers(), &relayScheduler{}, time.Unix(1000, 0)
		if sampled {
			for i := 0; i < 8; i++ {
				probeRound(ws, s, now.Add(time.Duration(i)*10*time.Second), []time.Duration{500 * time.Millisecond, 500 * time.Millisecond, 500 * time.Millisecond}, -1)
			}
			now = now.Add(71 * time.Second)
		}
		for i := 0; i < 120; i++ {
			if got := s.next(ws, i%3, now); got != i%3 {
				t.Fatalf("equal/unknown quality changed ready-relay coverage: sampled=%v chunk=%d index=%d", sampled, i, got)
			}
		}
	}
}

func TestAdaptiveDispatcherKeepsChunkOrderAndAllReadyConnections(t *testing.T) {
	c := &dispatchFixtureConn{input: make(chan []byte, 72*chunkSize), closed: make(chan struct{})}
	d := NewDispatcher(context.Background(), c, NewStats())
	d.EnableAdaptiveRelays()
	defer d.Shutdown()
	ws := qualityWorkers()
	now := time.Now()
	for i := 0; i < 5; i++ {
		probeRound(ws, d.adaptive.Load(), now.Add(time.Duration(i-4)*10*time.Second), []time.Duration{20 * time.Millisecond, 25 * time.Millisecond, 600 * time.Millisecond}, -1)
	}
	for _, w := range ws {
		w.SendCh = make(chan []byte, 72*chunkSize)
		d.Register(w)
	}
	for i := 0; i < 72*chunkSize; i++ {
		c.input <- []byte{byte(i >> 8), byte(i)}
	}
	deadline := time.Now().Add(2 * time.Second)
	for len(ws[0].SendCh)+len(ws[1].SendCh)+len(ws[2].SendCh) != 72*chunkSize {
		if time.Now().After(deadline) {
			t.Fatal("adaptive dispatcher lost fixture packets")
		}
		time.Sleep(time.Millisecond)
	}
	if len(*d.workers.Load()) != len(ws) {
		t.Fatal("adaptive selection unregistered live connections")
	}
	for i, w := range ws {
		want := 32 * chunkSize
		if i == 2 {
			want = 8 * chunkSize
		}
		if len(w.SendCh) != want {
			t.Fatalf("worker %d: got %d packets, want %d", i, len(w.SendCh), want)
		}
		for len(w.SendCh) > 0 {
			first := -1
			for j := 0; j < chunkSize; j++ {
				p := <-w.SendCh
				n := int(p[0])<<8 | int(p[1])
				if j == 0 {
					first = n
				}
				putPktBuf(p)
				if n != first+j {
					t.Fatal("quality selection changed order inside chunk8")
				}
			}
		}
	}
}

func TestRelayQualityForgetsUnregisteredSlotsAndIsRaceSafe(t *testing.T) {
	ws, s, now := qualityWorkers(), &relayScheduler{}, time.Now()
	var group sync.WaitGroup
	group.Add(1)
	go func() {
		defer group.Done()
		for i := 0; i < 100; i++ {
			ws[0].quality.observe(time.Millisecond, nil, now)
		}
	}()
	for i := 0; i < 100; i++ {
		s.next(ws, 0, now.Add(time.Duration(i)*time.Second))
	}
	group.Wait()
	remaining := []*WorkerSlot{ws[2]}
	s.next(remaining, 0, now.Add(101*time.Second))
	if len(s.states) != 1 {
		t.Fatal("unregistered relays leak into scheduler state")
	}
	if got := s.next(nil, 0, now); got != 0 {
		t.Fatal("empty pool must keep fallback safe")
	}
}

type bindingLossConn struct {
	net.PacketConn
	drop atomic.Bool
}

func (c *bindingLossConn) WriteTo(data []byte, to net.Addr) (int, error) {
	if c.drop.Load() && stun.IsMessage(data) {
		message := &stun.Message{Raw: data}
		if message.Decode() == nil && message.Type == stun.BindingRequest {
			return len(data), nil // Successful local write, actual remote loss.
		}
	}
	return c.PacketConn.WriteTo(data, to)
}

func TestRelayQualityUsesActualTURNBindingResultRatherThanSuccessfulUDPWrite(t *testing.T) {
	serverConn, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer serverConn.Close()
	server, err := turn.NewServer(turn.ServerConfig{Realm: "quality.test", PacketConnConfigs: []turn.PacketConnConfig{{
		PacketConn: serverConn, RelayAddressGenerator: &turn.RelayAddressGeneratorStatic{RelayAddress: net.ParseIP("127.0.0.1"), Address: "127.0.0.1"},
	}}})
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	address := serverConn.LocalAddr().String()
	conn, _, err := dialUDPTURN(context.Background(), []string{address}, 0, &TurnParams{})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	loss := &bindingLossConn{PacketConn: conn}
	client, err := turn.NewClient(&turn.ClientConfig{Conn: loss, STUNServerAddr: address, TURNServerAddr: address, RTO: 2 * time.Millisecond, Net: mobileNet{}})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if err = client.Listen(); err != nil {
		t.Fatal(err)
	}
	q := &relayQuality{}
	started := time.Now()
	_, err = client.SendBindingRequest()
	q.observe(time.Since(started), err, time.Now())
	if err != nil || q.snapshot().success != 1 {
		t.Fatalf("working TURN binding not observed: %v", err)
	}
	loss.drop.Store(true)
	for i := 0; i < 3; i++ {
		started = time.Now()
		_, err = client.SendBindingRequest()
		q.observe(time.Since(started), err, time.Now())
		if err == nil {
			t.Fatal("dropped binding was incorrectly considered delivered")
		}
	}
	if q.snapshot().failures != 3 {
		t.Fatal("actual remote timeouts did not reach quality state")
	}
	loss.drop.Store(false)
	started = time.Now()
	_, err = client.SendBindingRequest()
	q.observe(time.Since(started), err, time.Now())
	if err != nil || q.snapshot().failures != 0 {
		t.Fatalf("recovery from real packet loss not observed: %v", err)
	}
}
