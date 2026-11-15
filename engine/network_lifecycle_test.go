package main

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"
)

func TestWakeDoesNotLeaveAnUnreachableLTEAllocationActive(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	events := &iosNetworkEvents{}
	ready, done := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(done)
		calls := 0
		runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
			calls++
			if calls == 1 {
				close(ready)
				return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 1000}, nil
			}
			return nil, errors.New("LTE binding no longer answers")
		}, cancel, nil, events, nil)
	}()
	<-ready
	events.notify(false)
	select {
	case <-done:
	case <-time.After(250 * time.Millisecond):
		t.Fatal("wake kept an unreachable LTE channel registered indefinitely")
	}
	if ctx.Err() == nil {
		t.Fatal("failed allocation was not retired")
	}
}

func TestWakeKeepsTransientSTUNFailureAndLiveDTLSTraffic(t *testing.T) {
	for _, liveData := range []bool{false, true} {
		ctx, cancel := context.WithCancel(context.Background())
		events := &iosNetworkEvents{}
		activity := &iosSessionActivity{}
		activity.markReady()
		checked, done := make(chan int, 4), make(chan struct{})
		go func() {
			defer close(done)
			calls := 0
			runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
				calls++
				defer func() { checked <- calls }()
				if calls > 1 && (liveData || calls == 2) {
					if liveData {
						activity.markReceived()
					}
					return nil, errors.New("one missed STUN response")
				}
				return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 1000}, nil
			}, cancel, nil, events, activity)
		}()
		<-checked
		events.notify(false)
		wanted := 3
		if liveData {
			wanted = 2
		}
		for n := 1; n < wanted; n++ {
			select {
			case <-checked:
			case <-time.After(time.Second):
				t.Fatal("wake verification stalled")
			}
		}
		if ctx.Err() != nil {
			t.Errorf("healthy channel closed (live DTLS=%v)", liveData)
		}
		cancel()
		<-done
	}
}

func TestReboundNATCannotRemainRegisteredAsTheOldAllocation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ticks := make(chan time.Time, 1)
	ready := make(chan struct{}, 2)
	done := make(chan struct{})
	var calls int
	go func() {
		defer close(done)
		runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
			calls++
			ready <- struct{}{}
			return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 1000 + calls}, nil
		}, cancel, ticks, &iosNetworkEvents{}, nil)
	}()
	<-ready
	ticks <- time.Now()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("changed NAT mapping left stale worker active")
	}
	if ctx.Err() == nil {
		t.Fatal("old allocation was not invalidated")
	}
}

func TestWakePreservesHealthyMappingsAndNetworkChangeInvalidatesOldSockets(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	events := &iosNetworkEvents{}
	ready := make(chan struct{}, 3)
	done := make(chan struct{})
	go func() {
		defer close(done)
		runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
			ready <- struct{}{}
			return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 1000}, nil
		}, cancel, nil, events, nil)
	}()
	<-ready
	events.notify(false)
	select {
	case <-ready:
	case <-time.After(time.Second):
		t.Fatal("wake did not check NAT identity")
	}
	if ctx.Err() != nil {
		t.Fatal("healthy idle channel was reset on wake")
	}
	events.notify(true)
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("old physical-network socket stayed active")
	}
	if ctx.Err() == nil {
		t.Fatal("interface change did not invalidate old socket")
	}
}

func TestNewSessionDoesNotInheritAnOldNetworkChange(t *testing.T) {
	events := &iosNetworkEvents{}
	events.notify(true)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready, done := make(chan struct{}, 2), make(chan struct{})
	ticks := make(chan time.Time, 1)
	go func() {
		defer close(done)
		runIOSBindingLoop(ctx, 1, func() (net.Addr, error) {
			ready <- struct{}{}
			return &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 1000}, nil
		}, cancel, ticks, events, nil)
	}()
	<-ready
	ticks <- time.Now()
	select {
	case <-ready:
	case <-time.After(time.Second):
		t.Fatal("new session inherited a stale reset")
	}
	if ctx.Err() != nil {
		t.Fatal("new session was cancelled by an old network event")
	}
	cancel()
	<-done
}
