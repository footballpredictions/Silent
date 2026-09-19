package main

import (
	"math/rand"
	"strings"
	"time"
)

func shouldStopWorker(errStrLower string, attempt int) bool {
	_ = attempt
	return strings.Contains(errStrLower, "error 29") ||
		strings.Contains(errStrLower, "cannot create socket")
}

func isTurnQuotaError(err error) bool {
	if err == nil {
		return false
	}
	s := strings.ToLower(err.Error())
	return strings.Contains(s, "quota") ||
		strings.Contains(s, "486") ||
		strings.Contains(s, "квота")
}

func shouldRefreshTurnCreds(errStrLower string) bool {
	if strings.Contains(errStrLower, "quota") ||
		strings.Contains(errStrLower, "486") ||
		strings.Contains(errStrLower, "квота") {
		return false
	}
	if strings.Contains(errStrLower, "turn allocate") &&
		strings.Contains(errStrLower, "attribute not found") {
		return true
	}
	return strings.Contains(errStrLower, "turn allocate auth") ||
		strings.Contains(errStrLower, "invalid credential") ||
		strings.Contains(errStrLower, "stale nonce") ||
		strings.Contains(errStrLower, "allocation mismatch") ||
		strings.Contains(errStrLower, "error 508")
}

func sessionRetryDelay(sessErr error) time.Duration {
	if sessErr == nil {
		return time.Duration(5+rand.Intn(11)) * time.Second
	}
	if strings.Contains(sessErr.Error(), "WRAP_AUTH_TIMEOUT") {
		return time.Duration(300+rand.Intn(700)) * time.Millisecond
	}
	if isTurnQuotaError(sessErr) {
		return time.Duration(30+rand.Intn(31)) * time.Second
	}
	return time.Duration(5+rand.Intn(11)) * time.Second
}
