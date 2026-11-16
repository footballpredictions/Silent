package main

import (
	"context"
	"errors"
	"log"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// The server closes an established DTLS proxy after 90s without incoming
// application packets. Its close_notify may be lost while the phone sleeps;
// successful TURN control requests cannot recreate the old DTLS keys.
const iosDTLSServerIdleTimeout = 90 * time.Second

var errIOSDTLSSendGap = errors.New("DTLS: истёк серверный срок без отправки, нужен новый канал")

// Serialize all application writes (initial GETCONF, ping, access check and WG)
// so none can conceal an expired session by refreshing its last-send timestamp.
// Close deliberately uses the embedded Conn: cancellation must unblock a writer
// without waiting for this mutex. now is injectable only for local tests.
type iosDTLSConn struct {
	net.Conn
	sendMu       sync.Mutex
	now          func() time.Time
	onExpired    func()
	lastSentWall int64
	expired      bool
}

func newIOSDTLSConn(conn net.Conn, onExpired func()) *iosDTLSConn {
	return newIOSDTLSConnWithClock(conn, time.Now, onExpired)
}

func newIOSDTLSConnWithClock(conn net.Conn, now func() time.Time, onExpired func()) *iosDTLSConn {
	// Construction follows a successful handshake. Treat that as the initial
	// lease too: sleeping before GETCONF/the first ping must not bypass expiry.
	return &iosDTLSConn{Conn: conn, now: now, onExpired: onExpired, lastSentWall: now().UnixNano()}
}

func (c *iosDTLSConn) sendExpired(now time.Time) bool {
	// Compare Unix timestamps, not time.Time.Sub: Darwin's monotonic clock can
	// pause during system sleep while the remote server's lifetime continues.
	return now.UnixNano()-c.lastSentWall >= int64(iosDTLSServerIdleTimeout)
}

func (c *iosDTLSConn) Write(payload []byte) (int, error) {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	if c.expired {
		return 0, errIOSDTLSSendGap
	}
	if c.sendExpired(c.now()) {
		c.expireSend()
		return 0, errIOSDTLSSendGap
	}
	n, err := c.Conn.Write(payload)
	if err == nil && n == len(payload) {
		now := c.now()
		// A write already in progress when the process slept must not revive
		// an expired server session when it finally returns successfully.
		if c.sendExpired(now) {
			c.expireSend()
			return n, errIOSDTLSSendGap
		}
		c.lastSentWall = now.UnixNano()
	}
	return n, err
}

// Called only with sendMu held; emit the recovery reason once per session.
func (c *iosDTLSConn) expireSend() {
	c.expired = true
	if c.onExpired != nil {
		c.onExpired()
	}
}

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

func (e *iosNetworkEvents) notify(interfaceChanged bool) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	now := time.Now()
	elapsed := time.Duration(now.UnixNano() - e.lastProbe.UnixNano())
	if !interfaceChanged && !e.lastProbe.IsZero() && elapsed >= 0 && elapsed < 2*time.Second {
		return false
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
	return true
}

var iosPathEvents iosNetworkEvents

func refreshIOSTURNRelay(relay interface{}) error {
	if resumable, ok := relay.(interface{ Refresh() error }); ok {
		return resumable.Refresh()
	}
	return errors.New("TURN: библиотека не поддерживает продление после сна")
}

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
func runIOSBindingChecks(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc, activity *iosSessionActivity, resume func() error) {
	ticker := time.NewTicker(time.Duration(30+id%7) * time.Second)
	defer ticker.Stop()
	runIOSBindingLoop(ctx, id, probe, cancel, ticker.C, &iosPathEvents, activity, resume)
}

func runIOSBindingLoop(ctx context.Context, id int, probe func() (net.Addr, error), cancel context.CancelFunc,
	ticks <-chan time.Time, events *iosNetworkEvents, activity *iosSessionActivity, resume func() error) {
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
			if resume != nil {
				// STUN can succeed while the server's permission/channel has
				// expired during suspension. Renew those in place, rather than
				// counting this worker as healthy based only on its mapped IP.
				err := resume()
				if err != nil && ctx.Err() == nil {
					err = resume()
				}
				if ctx.Err() != nil {
					return
				}
				if err != nil {
					log.Printf("[ВОРКЕР #%d] TURN: сервер не подтвердил продление канала после сна", id)
					cancel()
					return
				}
				log.Printf("[ВОРКЕР #%d] TURN: разрешение и канал продлены после сна", id)
			}
		}
	}
}
