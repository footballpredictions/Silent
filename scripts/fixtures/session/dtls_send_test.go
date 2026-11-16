package main

import (
	"errors"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type recordingDTLSConn struct {
	writes      atomic.Int32
	fail        atomic.Bool
	duringWrite func()
}

func (c *recordingDTLSConn) Write(p []byte) (int, error) {
	c.writes.Add(1)
	if c.duringWrite != nil {
		c.duringWrite()
	}
	if c.fail.Load() {
		return 0, io.ErrUnexpectedEOF
	}
	return len(p), nil
}
func (*recordingDTLSConn) Read(p []byte) (int, error)       { return copy(p, "[Interface]\n"), nil }
func (*recordingDTLSConn) Close() error                     { return nil }
func (*recordingDTLSConn) LocalAddr() net.Addr              { return &net.UDPAddr{} }
func (*recordingDTLSConn) RemoteAddr() net.Addr             { return &net.UDPAddr{} }
func (*recordingDTLSConn) SetDeadline(time.Time) error      { return nil }
func (*recordingDTLSConn) SetWriteDeadline(time.Time) error { return nil }
func (*recordingDTLSConn) SetReadDeadline(time.Time) error  { return nil }

func newSendFixture() (*iosDTLSConn, *recordingDTLSConn, *fixtureWallClock) {
	raw, clock := &recordingDTLSConn{}, newFixtureClock()
	c := newIOSDTLSConnWithClock(raw, clock.now, nil)
	return c, raw, clock
}

func TestInitialGETCONFUsesTheSameSendGuard(t *testing.T) {
	c, raw, clock := newSendFixture()
	if _, err := RequestConfig(c, "0", "fixture", "fixture"); err != nil {
		t.Fatal(err)
	}
	if c.lastSentWall != clock.now().UnixNano() || raw.writes.Load() != 1 {
		t.Fatal("initial GETCONF bypassed successful-send tracking")
	}
	clock.advance(90 * time.Second)
	if _, err := RequestConfig(c, "0", "fixture", "fixture"); !errors.Is(err, errIOSDTLSSendGap) {
		t.Fatalf("expired GETCONF went through: %v", err)
	}
	if raw.writes.Load() != 1 {
		t.Fatal("expired GETCONF was emitted")
	}
}

func TestHandshakeLeaseExpiresBeforeTheFirstApplicationWrite(t *testing.T) {
	c, raw, clock := newSendFixture()
	clock.advance(90 * time.Second)
	if _, err := c.Write([]byte{0xff}); !errors.Is(err, errIOSDTLSSendGap) || raw.writes.Load() != 0 {
		t.Fatalf("first write revived expired handshake: %v", err)
	}
}

func TestFirstApplicationWriteSpanningSleepCannotRearmTheLease(t *testing.T) {
	c, raw, clock := newSendFixture()
	clock.advance(60 * time.Second)
	raw.duringWrite = func() { clock.advance(31 * time.Second) }
	if n, err := c.Write([]byte{1}); n != 1 || !errors.Is(err, errIOSDTLSSendGap) {
		t.Fatalf("first late write revived expired handshake: n=%d err=%v", n, err)
	}
	if _, err := c.Write([]byte{1}); !errors.Is(err, errIOSDTLSSendGap) || raw.writes.Load() != 1 {
		t.Fatal("first late write expiry was not sticky")
	}
}

func TestSendGuardMatchesTheServer90SecondBoundary(t *testing.T) {
	for _, gap := range []time.Duration{89 * time.Second, 90*time.Second - time.Nanosecond, 90 * time.Second, 91 * time.Second} {
		t.Run(gap.String(), func(t *testing.T) {
			c, raw, clock := newSendFixture()
			if _, err := c.Write([]byte{1}); err != nil {
				t.Fatal(err)
			}
			clock.advance(gap)
			_, err := c.Write([]byte{0xff})
			if gap < 90*time.Second {
				if err != nil || raw.writes.Load() != 2 {
					t.Fatalf("healthy send rejected: %v", err)
				}
			} else if !errors.Is(err, errIOSDTLSSendGap) || raw.writes.Load() != 1 {
				t.Fatalf("expired send emitted: err=%v writes=%d", err, raw.writes.Load())
			}
		})
	}
}

func TestFailedWriteDoesNotRefreshTheSuccessfulSendTime(t *testing.T) {
	c, raw, clock := newSendFixture()
	c.Write([]byte{1})
	clock.advance(60 * time.Second)
	raw.fail.Store(true)
	if _, err := c.Write([]byte{1}); !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatal(err)
	}
	raw.fail.Store(false)
	clock.advance(30 * time.Second)
	if _, err := c.Write([]byte{1}); !errors.Is(err, errIOSDTLSSendGap) {
		t.Fatal("failed send revived the session")
	}
	if raw.writes.Load() != 2 {
		t.Fatal("expired packet was emitted")
	}
}

func TestWriteWhichSpansSleepCannotReviveExpiredDTLS(t *testing.T) {
	c, raw, clock := newSendFixture()
	c.Write([]byte{1})
	clock.advance(60 * time.Second)
	raw.duringWrite = func() { clock.advance(31 * time.Second) }
	if n, err := c.Write([]byte{1}); n != 1 || !errors.Is(err, errIOSDTLSSendGap) {
		t.Fatalf("late successful write revived the old server state: n=%d err=%v", n, err)
	}
	if _, err := c.Write([]byte{1}); !errors.Is(err, errIOSDTLSSendGap) || raw.writes.Load() != 2 {
		t.Fatal("expiry was not sticky")
	}
}

func TestSuccessfulWriteRecordsCompletionWallTime(t *testing.T) {
	c, raw, clock := newSendFixture()
	raw.duringWrite = func() { clock.advance(time.Second) }
	if _, err := c.Write([]byte{1}); err != nil {
		t.Fatal(err)
	}
	if c.lastSentWall != clock.now().UnixNano() {
		t.Fatal("send time was recorded before success")
	}
}

func TestConcurrentWritersCannotRearmExpiredSession(t *testing.T) {
	c, raw, clock := newSendFixture()
	var expired atomic.Int32
	c.onExpired = func() { expired.Add(1) }
	c.Write([]byte{1})
	clock.advance(91 * time.Second)
	var wg sync.WaitGroup
	for i := 0; i < 64; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			p := []byte{0xff}
			if i%3 == 0 {
				p = getconfPayload("0", "fixture", "fixture")
			}
			if i%3 == 1 {
				p = []byte{1, 2, 3, 4}
			}
			if _, err := c.Write(p); !errors.Is(err, errIOSDTLSSendGap) {
				t.Errorf("expired concurrent write succeeded: %v", err)
			}
		}(i)
	}
	wg.Wait()
	clock.advance(-91 * time.Second) // Clock correction cannot undo observed expiry.
	if _, err := c.Write([]byte{1}); !errors.Is(err, errIOSDTLSSendGap) {
		t.Fatal("clock rollback revived an expired session")
	}
	if raw.writes.Load() != 1 || expired.Load() != 1 {
		t.Fatalf("writes=%d expiryEvents=%d", raw.writes.Load(), expired.Load())
	}
}

func TestConcurrentHealthyWritersRemainUsable(t *testing.T) {
	c, raw, _ := newSendFixture()
	var wg sync.WaitGroup
	for i := 0; i < 64; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for n := 0; n < 10; n++ {
				if _, err := c.Write([]byte{1}); err != nil {
					t.Error(err)
				}
			}
		}()
	}
	wg.Wait()
	if raw.writes.Load() != 640 || c.expired {
		t.Fatal("healthy concurrent sends lost data")
	}
}

type blockedDTLSConn struct {
	recordingDTLSConn
	started              chan struct{}
	closed               chan struct{}
	startOnce, closeOnce sync.Once
}

func (c *blockedDTLSConn) Write([]byte) (int, error) {
	c.startOnce.Do(func() { close(c.started) })
	<-c.closed
	return 0, net.ErrClosed
}
func (c *blockedDTLSConn) Close() error { c.closeOnce.Do(func() { close(c.closed) }); return nil }

func TestCloseUnblocksInFlightAndPendingWritersWithoutTakingSendMutex(t *testing.T) {
	raw := &blockedDTLSConn{started: make(chan struct{}), closed: make(chan struct{})}
	c := newIOSDTLSConn(raw, nil)
	var wg sync.WaitGroup
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := c.Write([]byte{1}); !errors.Is(err, net.ErrClosed) {
				t.Errorf("cancelled write: %v", err)
			}
		}()
	}
	<-raw.started
	closeDone := make(chan struct{})
	go func() { c.Close(); close(closeDone) }()
	select {
	case <-closeDone:
	case <-time.After(time.Second):
		t.Fatal("Close blocked behind sendMu")
	}
	writersDone := make(chan struct{})
	go func() { wg.Wait(); close(writersDone) }()
	select {
	case <-writersDone:
	case <-time.After(time.Second):
		t.Fatal("cancellation did not release pending writers")
	}
}
