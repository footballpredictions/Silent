package main

import (
	"context"
	"log"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

type iosNetworkSnapshot struct {
	changed    <-chan struct{}
	generation uint64
	forced     uint64
}

type iosNetworkEvents struct {
	mu         sync.Mutex
	signal     chan struct{}
	generation uint64
	forced     uint64
	lastProbe  time.Time
}

func (e *iosNetworkEvents) snapshot() iosNetworkSnapshot {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.signal == nil {
		e.signal = make(chan struct{})
	}
	return iosNetworkSnapshot{e.signal, e.generation, e.forced}
}

func (e *iosNetworkEvents) notify(interfaceChanged bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	now := time.Now()
	elapsed := time.Duration(now.UnixNano() - e.lastProbe.UnixNano())
	if !interfaceChanged && !e.lastProbe.IsZero() && elapsed >= 0 && elapsed < 2*time.Second {
		return
	}
	e.lastProbe = now
	e.generation++
	if interfaceChanged {
		e.forced = e.generation
	}
	if e.signal != nil {
		close(e.signal)
	}
	e.signal = make(chan struct{})
}

var iosPathEvents iosNetworkEvents

// Successful DTLS receives are independent evidence that the data path works,
// even when the TURN server temporarily misses a separate STUN request.
type iosSessionActivity struct {
	received atomic.Uint64
	ready    atomic.Bool
}

func (a *iosSessionActivity) markReceived() { a.received.Add(1) }
func (a *iosSessionActivity) markReady()    { a.ready.Store(true) }

// DTLS already sends a packet every 15s. Separate STUN binding requests every
// 10s per worker were redundant; keep the NAT identity check at a lower rate,
// and run it immediately on wake. A physical interface change invalidates the
// UDP socket itself, not the WireGuard device or iOS VPN profile.
func runIOSBindingChecks(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc, activity *iosSessionActivity) {
	ticker := time.NewTicker(time.Duration(30+id%7) * time.Second)
	defer ticker.Stop()
	runIOSBindingLoop(ctx, id, probe, cancel, ticker.C, &iosPathEvents, activity)
}

func runIOSBindingLoop(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc,
	ticks <-chan time.Time, events *iosNetworkEvents, activity *iosSessionActivity) {
	snapshot := events.snapshot()
	var mapped string
	var previousReceive uint64
	failures := 0
	check := func() bool {
		if ctx.Err() != nil {
			return false
		}
		address, err := probe()
		if ctx.Err() != nil {
			return false
		}
		if err != nil || address == nil {
			var received uint64
			if activity != nil {
				received = activity.received.Load()
			}
			if received != previousReceive || (mapped == "" && (activity == nil || !activity.ready.Load())) {
				failures = 0
			} else {
				failures++
			}
			previousReceive = received
			if failures >= 2 {
				log.Printf("[ВОРКЕР #%d] TURN: канал не отвечает на повторную проверку после потери сети", id)
				cancel()
				return false
			}
			return true
		} // A lone STUN timeout is not proof that DTLS is dead.
		failures = 0
		if activity != nil {
			previousReceive = activity.received.Load()
		}
		current := address.String()
		if mapped != "" && mapped != current {
			log.Printf("[ВОРКЕР #%d] TURN: NAT изменился, старый канал недействителен", id)
			cancel()
			return false
		}
		mapped = current
		return true
	}
	verify := func() bool {
		if !check() {
			return false
		}
		// Confirm an unanswered probe immediately instead of waiting another
		// full periodic interval after wake. Healthy DTLS traffic vetoes expiry.
		return failures == 0 || check()
	}
	if !verify() {
		return
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticks:
			if !verify() {
				return
			}
		case <-snapshot.changed:
			next := events.snapshot()
			if next.forced > snapshot.generation {
				log.Printf("[ВОРКЕР #%d] TURN: физическая сеть изменилась, нужен новый сокет", id)
				cancel()
				return
			}
			snapshot = next
			if activity != nil {
				previousReceive = activity.received.Load()
			}
			// Spread 63 wake probes instead of creating one radio/CPU burst.
			timer := time.NewTimer(time.Duration(id%63) * 50 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
			if !verify() {
				return
			}
		}
	}
}
