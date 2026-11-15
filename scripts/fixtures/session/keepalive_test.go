package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log"
	"net"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type testKeepaliveConn struct {
	failPing bool
	failConf bool
	writes   chan struct{}
}

type interruptedWrite struct{ cancel context.CancelFunc }

func TestOriginalRelayFailureIsNotHiddenByDTLSCancellation(t *testing.T) {
	for _, cancelled := range []bool{false, true} {
		ctx, cancel := context.WithCancel(context.Background())
		if cancelled {
			cancel()
		}
		var output bytes.Buffer
		previous := log.Writer()
		log.SetOutput(&output)
		reportRelayReadFailure(ctx, io.ErrUnexpectedEOF)
		log.SetOutput(previous)
		cancel()
		if cancelled && output.Len() != 0 {
			t.Fatal("cancelled relay reported another error")
		}
		if !cancelled && !strings.Contains(output.String(), "Ошибка TURN Reader") {
			t.Fatal("original relay read failure was hidden")
		}
	}
}

func (*interruptedWrite) SetWriteDeadline(time.Time) error { return nil }
func (c *interruptedWrite) Write([]byte) (int, error) {
	if c.cancel != nil {
		c.cancel()
	}
	return 0, io.ErrClosedPipe
}

func TestIntentionalSessionCancellationDoesNotReportATransportFailure(t *testing.T) {
	for _, writer := range []bool{true, false} {
		for _, intentional := range []bool{true, false} {
			var output bytes.Buffer
			previous := log.Writer()
			log.SetOutput(&output)
			parent, cancel := context.WithCancel(context.Background())
			connection := &interruptedWrite{}
			if intentional {
				connection.cancel = cancel
			}
			var done <-chan struct{}
			var stop context.CancelFunc
			if writer {
				packets := make(chan []byte, 1)
				packets <- []byte{1, 2}
				_, stop, done = launchWriter(parent, connection, packets)
			} else {
				_, stop, done = launchKeepalive(parent, connection, false)
			}
			select {
			case <-done:
			case <-time.After(time.Second):
				t.Fatal("interrupted session did not finish")
			}
			stop()
			cancel()
			log.SetOutput(previous)
			if intentional && output.Len() != 0 {
				t.Errorf("intentional cancel reported a red failure (writer=%v): %s", writer, output.String())
			}
			if !intentional && output.Len() == 0 {
				t.Errorf("real transport failure was hidden (writer=%v)", writer)
			}
		}
	}
}

func (c *testKeepaliveConn) SetWriteDeadline(time.Time) error { return nil }
func (c *testKeepaliveConn) Write(packet []byte) (int, error) {
	if (len(packet) == 1 && c.failPing) || (len(packet) > 1 && c.failConf) {
		return 0, io.ErrClosedPipe
	}
	select {
	case c.writes <- struct{}{}:
	default:
	}
	return len(packet), nil
}

func TestFailedKeepaliveReleasesRegisteredWorker(t *testing.T) {
	for _, kind := range []string{"ping", "access-check"} {
		t.Run(kind, func(t *testing.T) {
			connection := &testKeepaliveConn{failPing: kind == "ping", failConf: kind == "access-check"}
			ctx, cancel, done := launchKeepalive(context.Background(), connection, true)
			defer cancel()
			select {
			case <-done:
			case <-time.After(time.Second):
				t.Fatal("failed keepalive did not finish")
			}
			if ctx.Err() == nil {
				t.Fatal("dead DTLS socket left session alive: reader/writer wait and worker remains registered")
			}
		})
	}
}

func TestHealthyIdleSessionStaysConnected(t *testing.T) {
	connection := &testKeepaliveConn{writes: make(chan struct{}, 1)}
	ctx, cancel, done := launchKeepalive(context.Background(), connection, false)
	defer cancel()
	select {
	case <-connection.writes:
	case <-time.After(time.Second):
		t.Fatal("idle session did not send keepalive")
	}
	if ctx.Err() != nil {
		t.Fatal("healthy idle session was disconnected")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("user stop did not release keepalive")
	}
}

func TestTURNRenewalFailureReleasesSession(t *testing.T) {
	for _, event := range []string{"Failed to refresh allocation: %s", "Failed to refresh permissions: %s"} {
		t.Run(event, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			sessionTURNLogger(ctx, cancel).Warnf(event, io.ErrClosedPipe)
			if ctx.Err() == nil {
				t.Fatal("TURN renewal failed but allocation remained registered as a working session")
			}
		})
	}
}

func TestUnrelatedTURNWarningDoesNotDropHealthySession(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sessionTURNLogger(ctx, cancel).Warnf("Unrelated transient warning: %s", io.EOF)
	if ctx.Err() != nil {
		t.Fatal("unrelated library warning dropped a healthy channel")
	}
}

func TestTURNFailureJournalContainsCodeButNoServerSecrets(t *testing.T) {
	var output bytes.Buffer
	previous := log.Writer()
	log.SetOutput(&output)
	defer log.SetOutput(previous)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sessionTURNLogger(ctx, cancel).Warnf("Failed to refresh allocation: %s", errors.New("TURN refresh rejected (437)"))
	if !strings.Contains(output.String(), "код 437") {
		t.Fatal("renewal failure code was lost")
	}
	ctx, cancel2 := context.WithCancel(context.Background())
	defer cancel2()
	sessionTURNLogger(ctx, cancel2).Warnf("Failed to refresh allocation: %s", errors.New("timeout secret-token address=192.0.2.1"))
	if strings.Contains(output.String(), "secret-token") || strings.Contains(output.String(), "192.0.2.1") {
		t.Fatal("TURN diagnostics exposed original library error")
	}
}

type testTURNConnection struct {
	calls     atomic.Int32
	refreshes atomic.Int32
	rebind    bool
	noReply   bool
	ready     chan int32
}

func (c *testTURNConnection) Refresh() error { c.refreshes.Add(1); return nil }

func TestActualSessionWakeRefreshesTURNNotJustSTUN(t *testing.T) {
	connection := &testTURNConnection{ready: make(chan int32, 8)}
	ctx, cancel, done := launchBinding(context.Background(), connection)
	defer cancel()
	<-connection.ready
	iosPathEvents.mu.Lock()
	iosPathEvents.lastProbe = time.Time{}
	iosPathEvents.mu.Unlock()
	iosPathEvents.notify(false)
	deadline := time.After(time.Second)
	for connection.refreshes.Load() == 0 {
		select {
		case <-deadline:
			t.Fatal("session wake only checked STUN; expired TURN data path was not renewed")
		case <-time.After(time.Millisecond):
		}
	}
	if ctx.Err() != nil {
		t.Fatal("successful renewal restarted the session")
	}
	cancel()
	<-done
}

func (c *testTURNConnection) SendBindingRequest() (net.Addr, error) {
	n := c.calls.Add(1)
	if c.noReply && n > 1 {
		return nil, context.DeadlineExceeded
	}
	port := 1000
	if c.rebind && n > 1 {
		port = 2000
	}
	select {
	case c.ready <- n:
	default:
	}
	return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: port}, nil
}

func TestActualBindingLoopRetiresAnUnreachableAllocation(t *testing.T) {
	connection := &testTURNConnection{noReply: true, ready: make(chan int32, 4)}
	ctx, cancel, done := launchBinding(context.Background(), connection)
	defer cancel()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("unreachable TURN channel was kept active without data")
	}
	<-done
}

func TestActualBindingLoopInvalidatesReboundNAT(t *testing.T) {
	connection := &testTURNConnection{rebind: true, ready: make(chan int32, 2)}
	ctx, cancel, done := launchBinding(context.Background(), connection)
	defer cancel()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("NAT changed but the actual session kept its expired TURN allocation")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("binding loop did not release cancelled session")
	}
}

func TestActualBindingLoopKeepsStableNATAlive(t *testing.T) {
	connection := &testTURNConnection{ready: make(chan int32, 4)}
	ctx, cancel, done := launchBinding(context.Background(), connection)
	defer cancel()
	for i := 0; i < 3; i++ {
		select {
		case <-connection.ready:
		case <-time.After(time.Second):
			t.Fatal("binding probe stopped")
		}
	}
	if ctx.Err() != nil {
		t.Fatal("stable NAT mapping was disconnected")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("binding loop ignored user stop")
	}
}

type testWorkerSlot struct{}
type testDispatcher struct {
	removed chan struct{}
	calls   atomic.Int32
}

func (*testDispatcher) Register(*testWorkerSlot) {}
func (d *testDispatcher) Unregister(*testWorkerSlot) {
	if d.calls.Add(1) == 1 {
		close(d.removed)
	}
}

func TestCancelledWorkerStopsReceivingPacketsBeforeCleanupFinishes(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	d := &testDispatcher{removed: make(chan struct{})}
	ready, hold, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	defer func() { close(hold); <-done }()
	go func() { defer close(done); holdRegistration(ctx, d, &testWorkerSlot{}, ready, hold) }()
	<-ready
	cancel()
	select {
	case <-d.removed:
	case <-time.After(time.Second):
		t.Fatal("dead worker stayed registered while TURN cleanup was blocked")
	}
	if d.calls.Load() != 1 {
		t.Fatal("worker unregistered more than once")
	}
}
