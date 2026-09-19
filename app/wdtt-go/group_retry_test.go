package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestShouldNotStopWorkerOnTurnRetransmit(t *testing.T) {
	err := "turn allocate: all retransmissions failed"
	if shouldStopWorker(err, 3) {
		t.Fatal("TURN retransmit must not kill the worker (hive ramp 55/63)")
	}
	if shouldStopWorker(err, 8) {
		t.Fatal("TURN retransmit still retryable after 8 attempts")
	}
}

func TestShouldStopWorkerOnStunDeath(t *testing.T) {
	if !shouldStopWorker("cannot create socket: error 29", 1) {
		t.Fatal("STUN death must stop the worker")
	}
}

func TestWrapAuthTimeoutRetriesFast(t *testing.T) {
	d := sessionRetryDelay(fmt.Errorf("WRAP_AUTH_TIMEOUT: DTLS handshake timeout (повтор)"))
	if d < 300*time.Millisecond || d > time.Second {
		t.Fatalf("WRAP retry want 300-1000ms, got %v", d)
	}
}

func TestOtherSessionErrorRetriesSeconds(t *testing.T) {
	d := sessionRetryDelay(fmt.Errorf("TURN Allocate: timeout"))
	if d < 5*time.Second || d > 16*time.Second {
		t.Fatalf("normal retry want 5-16s, got %v", d)
	}
}

func TestQuotaErrorWaitsHalfMinuteWithoutRefresh(t *testing.T) {
	err := fmt.Errorf("TURN квота: 486 Allocate Quota")
	if !isTurnQuotaError(err) {
		t.Fatal("486 quota must be detected")
	}
	if shouldRefreshTurnCreds(strings.ToLower(err.Error())) {
		t.Fatal("quota must not invalidate TURN creds")
	}
	d := sessionRetryDelay(err)
	if d < 30*time.Second || d > 61*time.Second {
		t.Fatalf("quota wait want 30-61s, got %v", d)
	}
}
