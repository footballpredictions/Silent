package main

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestGroupCredentialsRecoverTemporaryError(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	attempts, handoffs := 0, 0
	wanted := &Credentials{User: "test-user", Pass: "test-pass", TurnURLs: []string{"turn:127.0.0.1:3478"}}
	got, err := acquireGroupCredentials(ctx, 7, func(context.Context) (*Credentials, error) {
		attempts++
		if attempts == 1 {
			inner := &vkCallsVKAPIError{Code: 10, Message: "Internal server error"}
			return nil, newVKCallsFailure("step3 messages.getAnonymCallToken", vkCallsAPIErrorKind(inner), inner)
		}
		return wanted, nil
	}, func() { handoffs++ })
	if err != nil || got != wanted || attempts != 2 || handoffs != 1 {
		t.Fatalf("temporary failure permanently lost group: attempts=%d handoffs=%d creds=%v err=%v", attempts, handoffs, got != nil, err)
	}
	if ctx.Err() != nil {
		t.Fatal("credential recovery must keep the group session active")
	}
}

func TestGroupCredentialsCancelBackoff(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	attempts := 0
	_, err := acquireGroupCredentials(ctx, 1, func(context.Context) (*Credentials, error) {
		attempts++
		inner := &vkCallsVKAPIError{Code: 10, Message: "Internal server error"}
		return nil, newVKCallsFailure("step3", vkCallsAPIErrorKind(inner), inner)
	}, cancel)
	if !errors.Is(err, context.Canceled) || attempts != 1 {
		t.Fatalf("cancel did not interrupt credential backoff: calls=%d err=%v", attempts, err)
	}
}

func TestGroupCredentialsDoesNotRetryUnavailableCall(t *testing.T) {
	attempts, handoffs := 0, 0
	wanted := &CallUnavailableError{Code: 951, Message: "call not found"}
	_, err := acquireGroupCredentials(context.Background(), 1, func(context.Context) (*Credentials, error) { attempts++; return nil, wanted }, func() { handoffs++ })
	if err != wanted || attempts != 1 || handoffs != 0 {
		t.Fatalf("dead call was retried: calls=%d handoffs=%d err=%v", attempts, handoffs, err)
	}
}
