package main

import (
	"bytes"
	"context"
	"io"
	"log"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/pion/dtls/v3"
	"github.com/pion/dtls/v3/pkg/crypto/selfsign"
	dtlsnet "github.com/pion/dtls/v3/pkg/net"
	pionudp "github.com/pion/transport/v4/udp"
)

func TestMain(m *testing.M) { log.SetOutput(io.Discard); m.Run() }

type fixtureWallClock struct{ unix atomic.Int64 }

func newFixtureClock() *fixtureWallClock {
	c := &fixtureWallClock{}
	c.unix.Store(time.Now().UnixNano())
	return c
}
func (c *fixtureWallClock) now() time.Time          { return time.Unix(0, c.unix.Load()) }
func (c *fixtureWallClock) advance(d time.Duration) { c.unix.Add(int64(d)) }

// A suspended provider cannot run either timer. Resume them explicitly, after
// advancing WALL time; Darwin monotonic time need not advance during sleep.
type fixtureTicker struct{ C <-chan time.Time }

func (*fixtureTicker) Stop() {}

type fixtureTicks struct {
	ping, access chan time.Time
	sent         chan struct{}
	settle       func()
}

func newFixtureTicks() *fixtureTicks {
	return &fixtureTicks{ping: make(chan time.Time, 8), access: make(chan time.Time, 8), sent: make(chan struct{}, 32)}
}
func (t *fixtureTicks) pingTicker() *fixtureTicker   { return &fixtureTicker{t.ping} }
func (t *fixtureTicks) accessTicker() *fixtureTicker { return &fixtureTicker{t.access} }

type gatedSocket struct {
	net.PacketConn
	drop   *atomic.Bool
	writes atomic.Int32
	sent   chan struct{}
}

func (g *gatedSocket) WriteTo(p []byte, a net.Addr) (int, error) {
	g.writes.Add(1)
	if g.drop != nil && g.drop.Load() {
		return len(p), nil
	}
	n, err := g.PacketConn.WriteTo(p, a)
	if err == nil && g.sent != nil {
		select {
		case g.sent <- struct{}{}:
		default:
		}
	}
	return n, err
}

type gatedListener struct {
	dtlsnet.PacketListener
	drop *atomic.Bool
}

func (g *gatedListener) Accept() (net.PacketConn, net.Addr, error) {
	p, a, err := g.PacketListener.Accept()
	if err != nil {
		return p, a, err
	}
	return &gatedSocket{PacketConn: p, drop: g.drop}, a, nil
}

type testWorkerSlot struct{ SendCh chan []byte }
type testDispatcher struct {
	ReturnCh   chan []byte
	registered atomic.Int32
}

func (d *testDispatcher) Register(*testWorkerSlot)   { d.registered.Add(1) }
func (d *testDispatcher) Unregister(*testWorkerSlot) { d.registered.Add(-1) }

// Only account/access side effects around the real server proxy are stubbed.
var totalBytesFromClient, totalBytesToClient, mainPassUp, mainPassDown int64
var activeDevicesMu, dbMutex sync.Mutex
var activeDevices = map[string]int{}

type passwordEntry struct{ UpBytes, DownBytes int64 }

var db = struct{ Passwords map[string]*passwordEntry }{map[string]*passwordEntry{}}

func getBuf() *[]byte                             { p := make([]byte, 2048); return &p }
func putBuf(*[]byte)                              {}
func reportDeviceOnline(string, bool)             {}
func deviceVpnAllowed(string) bool                { return true }
func denyNoSubscription(net.Conn, string, string) {}
func isPasswordExpired(*passwordEntry) bool       { return false }
func isGetconfPacket(b []byte, n int) bool        { return strings.HasPrefix(string(b[:n]), "GETCONF:") }
func isNetTimeout(err error) bool                 { e, ok := err.(net.Error); return ok && e.Timeout() }

type idleServerFixture struct {
	ctx       context.Context
	listener  net.Listener
	drop      atomic.Bool
	firstDone chan struct{}
	accepted  atomic.Int32
	echo      net.PacketConn
}

func newIdleServerFixture(t *testing.T) *idleServerFixture {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	f := &idleServerFixture{ctx: ctx, firstDone: make(chan struct{})}
	outer, err := pionudp.Listen("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	cert, err := selfsign.GenerateSelfSigned()
	if err != nil {
		cancel()
		outer.Close()
		t.Fatal(err)
	}
	f.listener, err = dtls.NewListenerWithOptions(&gatedListener{dtlsnet.PacketListenerFromListener(outer), &f.drop},
		dtls.WithCertificates(cert), dtls.WithExtendedMasterSecret(dtls.RequireExtendedMasterSecret),
		dtls.WithCipherSuites(dtls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256), dtls.WithConnectionIDGenerator(dtls.RandomCIDGenerator(8)))
	if err != nil {
		cancel()
		outer.Close()
		t.Fatal(err)
	}
	f.echo, err = net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		cancel()
		f.listener.Close()
		t.Fatal(err)
	}
	go func() {
		b := make([]byte, 2048)
		for {
			n, a, e := f.echo.ReadFrom(b)
			if e != nil {
				return
			}
			_, _ = f.echo.WriteTo(b[:n], a)
		}
	}()
	var handlers sync.WaitGroup
	acceptDone := make(chan struct{})
	go func() {
		defer close(acceptDone)
		for {
			c, e := f.listener.Accept()
			if e != nil {
				return
			}
			n := f.accepted.Add(1)
			handlers.Add(1)
			go func() {
				defer handlers.Done()
				if n == 1 {
					defer close(f.firstDone)
				}
				defer c.Close()
				if c.(*dtls.Conn).HandshakeContext(ctx) != nil {
					return
				}
				runActualServerProxy(ctx, c, f.echo.LocalAddr().String())
			}()
		}
	}()
	t.Cleanup(func() { cancel(); f.listener.Close(); <-acceptDone; handlers.Wait(); f.echo.Close() })
	return f
}
func (f *idleServerFixture) client(t *testing.T, d *testDispatcher, clock *fixtureWallClock) (context.Context, *testWorkerSlot, *fixtureTicks) {
	t.Helper()
	u, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ticks := newFixtureTicks()
	transport := &gatedSocket{PacketConn: u, sent: ticks.sent}
	c, err := dtls.Client(transport, f.listener.Addr(), &dtls.Config{InsecureSkipVerify: true, ExtendedMasterSecret: dtls.RequireExtendedMasterSecret,
		CipherSuites: []dtls.CipherSuiteID{dtls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256}, ConnectionIDGenerator: dtls.OnlySendCIDGenerator()})
	if err != nil {
		u.Close()
		t.Fatal(err)
	}
	if err = c.HandshakeContext(f.ctx); err != nil {
		c.Close()
		t.Fatal(err)
	}
	slot := &testWorkerSlot{SendCh: make(chan []byte, 8)}
	ctx, cancel, done := launchActualClient(f.ctx, c, d, slot, &iosSessionActivity{}, clock, ticks)
	t.Cleanup(func() { cancel(); <-done; c.Close(); u.Close() })
	return ctx, slot, ticks
}
func assertEcho(t *testing.T, d *testDispatcher, slot *testWorkerSlot, payload []byte) {
	t.Helper()
	slot.SendCh <- payload
	select {
	case got := <-d.ReturnCh:
		if !bytes.Equal(got, payload) {
			t.Fatalf("echo %x, want %x", got, payload)
		}
	case <-time.After(time.Second):
		t.Fatal("actual DTLS/server UDP proxy did not return data")
	}
}

func TestSleepingPeerExpiresAndFreshDTLSRestoresTwoWayData(t *testing.T) {
	f := newIdleServerFixture(t)
	d := &testDispatcher{ReturnCh: make(chan []byte, 8)}
	clock := newFixtureClock()
	ctx, slot, ticks := f.client(t, d, clock)
	assertEcho(t, d, slot, []byte{1, 2, 3, 4})
	f.drop.Store(true) // The sleeping radio loses the server's close_notify.
	select {
	case <-f.firstDone:
	case <-time.After(time.Second):
		t.Fatal("actual server proxy did not expire")
	}
	f.drop.Store(false)
	// Control-plane success is independent of the lost DTLS state.
	events := &iosNetworkEvents{}
	probed, renewed := make(chan struct{}, 8), make(chan struct{}, 8)
	go runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
		probed <- struct{}{}
		return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 41000}, nil
	},
		func() { t.Error("successful STUN/Refresh unexpectedly retired the session") }, make(chan time.Time), events, &iosSessionActivity{}, func() error { renewed <- struct{}{}; return nil })
	<-probed
	events.notify(false)
	select {
	case <-renewed:
	case <-time.After(time.Second):
		t.Fatal("TURN wake control did not succeed")
	}
	clock.advance(91 * time.Second)
	ticks.ping <- clock.now()
	ticks.access <- clock.now()
	slot.SendCh <- []byte{5, 6, 7, 8}
	select {
	case <-ctx.Done():
	case <-time.After(150 * time.Millisecond):
		t.Fatalf("data plane dead, worker still alive after server90s expiry: registered=%d, STUN/Refresh=success, accepted=%d", d.registered.Load(), f.accepted.Load())
	}
	until := time.Now().Add(time.Second)
	for d.registered.Load() != 0 && time.Now().Before(until) {
		time.Sleep(time.Millisecond)
	}
	if d.registered.Load() != 0 {
		t.Fatal("expired worker remains registered")
	}
	// The normal worker loop makes a fresh DTLS session, keeping its dispatcher.
	fresh, slot2, _ := f.client(t, d, clock)
	assertEcho(t, d, slot2, []byte{9, 10, 11, 12})
	if fresh.Err() != nil || d.registered.Load() != 1 {
		t.Fatal("replacement worker is not ready")
	}
}

func TestHealthyIdleUsesSuccessfulSendsWithoutNeedingReplies(t *testing.T) {
	f := newIdleServerFixture(t)
	d := &testDispatcher{ReturnCh: make(chan []byte, 8)}
	clock := newFixtureClock()
	ctx, slot, ticks := f.client(t, d, clock)
	assertEcho(t, d, slot, []byte{1, 2, 3, 4})
	for len(ticks.sent) > 0 {
		<-ticks.sent
	}
	for i := 0; i < 6; i++ {
		clock.advance(30 * time.Second)
		ticks.ping <- clock.now()
		select {
		case <-ticks.sent:
		case <-time.After(time.Second):
			t.Fatal("healthy ping was not sent")
		}
		if ticks.settle != nil {
			ticks.settle()
		}
	}
	assertEcho(t, d, slot, []byte{5, 6, 7, 8})
	if ctx.Err() != nil || d.registered.Load() != 1 {
		t.Fatal("healthy idle without ping replies was reset")
	}
}

func TestBelowServerIdleThresholdPreservesTheSameSession(t *testing.T) {
	f := newIdleServerFixture(t)
	d := &testDispatcher{ReturnCh: make(chan []byte, 8)}
	clock := newFixtureClock()
	ctx, slot, _ := f.client(t, d, clock)
	assertEcho(t, d, slot, []byte{1, 2, 3, 4})
	clock.advance(89 * time.Second)
	assertEcho(t, d, slot, []byte{5, 6, 7, 8})
	if ctx.Err() != nil || f.accepted.Load() != 1 {
		t.Fatal("subthreshold pause replaced healthy DTLS")
	}
}
