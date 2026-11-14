package main

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

func TestIOSRelayUsesNextHashAfterEarlyFailure(t *testing.T) {
	var attempted []string
	got, err := tryIOSRelayHashes(context.Background(), []string{"dead", "working", "unused"}, func(_ context.Context, hash string, budget time.Duration) (string, error) {
		attempted = append(attempted, hash)
		if budget != 15*time.Second {
			t.Fatalf("unexpected attempt budget %s", budget)
		}
		if hash == "dead" {
			return "", errors.New("workers exited before config")
		}
		return "valid config", nil
	})
	if err != nil || got != "valid config" || !reflect.DeepEqual(attempted, []string{"dead", "working"}) {
		t.Fatalf("got %q %v, attempted %v", got, err, attempted)
	}
}

func TestIOSRelayDoesNotRetryAfterCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	calls := 0
	_, err := tryIOSRelayHashes(ctx, []string{"first", "second"}, func(_ context.Context, _ string, _ time.Duration) (string, error) {
		calls++
		cancel()
		return "", errors.New("workers cancelled")
	})
	if calls != 1 || !errors.Is(err, context.Canceled) {
		t.Fatalf("got %d attempts, %v", calls, err)
	}
}

func TestIOSWorkerPlan(t *testing.T) {
	for _, tt := range []struct {
		requested, hashes, groups int
	}{{3, 1, 1}, {63, 1, 9}, {63, 2, 18}, {63, 3, 21}, {108, 4, 21}, {10, 4, 3}} {
		if got := iosWorkerGroupCount(tt.requested, tt.hashes); got != tt.groups {
			t.Errorf("%d workers, %d hashes: got %d groups, want %d", tt.requested, tt.hashes, got, tt.groups)
		}
	}
}
