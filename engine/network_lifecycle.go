package main

import (
	"context"
	"log"
	"net"
	"sync"
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

// DTLS already sends a packet every 15s. Separate STUN binding requests every
// 10s per worker were redundant; keep the NAT identity check at a lower rate,
// and run it immediately on wake. A physical interface change invalidates the
// UDP socket itself, not the WireGuard device or iOS VPN profile.
func runIOSBindingChecks(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc) {
	ticker := time.NewTicker(time.Duration(30+id%7) * time.Second)
	defer ticker.Stop()
	runIOSBindingLoop(ctx, id, probe, cancel, ticker.C, &iosPathEvents)
}

func runIOSBindingLoop(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc,
	ticks <-chan time.Time, events *iosNetworkEvents) {
	snapshot := events.snapshot()
	var mapped string
	check := func() bool {
		if ctx.Err() != nil {
			return false
		}
		address, err := probe()
		if ctx.Err() != nil {
			return false
		}
		if err != nil || address == nil {
			return true
		} // A lone STUN timeout is not proof that DTLS is dead.
		current := address.String()
		if mapped != "" && mapped != current {
			log.Printf("[ВОРКЕР #%d] TURN: NAT изменился, старый канал недействителен", id)
			cancel()
			return false
		}
		mapped = current
		return true
	}
	if !check() {
		return
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticks:
			if !check() {
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
			// Spread 63 wake probes instead of creating one radio/CPU burst.
			timer := time.NewTimer(time.Duration(id%63) * 50 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
			if !check() {
				return
			}
		}
	}
}
