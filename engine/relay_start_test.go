package main

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

func TestIOSWorkerPlanRespectsGlobalAndPerHashLimits(t *testing.T) {
	for _, tc := range []struct {
		hashes    []string
		requested int
		want      int
	}{
		{[]string{"a", "b", "c", "d"}, 108, 63},
		{[]string{"a", "b"}, 63, 54},
		{[]string{"a"}, 63, 27},
		{[]string{"a"}, 3, 3},
		{[]string{"a", "b"}, 7, 7},
	} {
		first := tc.hashes[len(tc.hashes)-1]
		groups := planIOSWorkerGroups(tc.hashes, first, tc.requested, 3)
		if len(groups) == 0 || groups[0].hash != first {
			t.Fatal("ramp must start with the relay that returned GETCONF")
		}
		total := 0
		counts := map[string]int{}
		for _, group := range groups {
			if group.size < 1 || group.size > 3 || group.firstID != total+1 {
				t.Fatalf("invalid group layout: %+v", group)
			}
			total += group.size
			counts[group.hash] += group.size
			if counts[group.hash] > 27 {
				t.Fatalf("hash assigned over 27 workers: %v", counts)
			}
		}
		if total != tc.want || len(counts) != len(tc.hashes) {
			t.Fatalf("got %d workers across %d hashes, want %d across %d", total, len(counts), tc.want, len(tc.hashes))
		}
	}
}

func TestIOSRelayUsesNextHashAfterEarlyFailure(t *testing.T) {
	var attempted []string
	got, err := tryIOSRelayHashes(context.Background(), []string{"dead", "working", "unused"}, func(_ context.Context, hash string, budget time.Duration) (string, error) {
		attempted = append(attempted, hash)
		if hash == "dead" {
			if budget >= 15*time.Second {
				t.Fatalf("first hash delayed failover by %s", budget)
			}
			return "", errors.New("workers exited before config")
		}
		if budget != 15*time.Second {
			t.Fatalf("reserve hash lost its full budget: %s", budget)
		}
		return "valid config", nil
	})
	if err != nil || got != "valid config" || !reflect.DeepEqual(attempted, []string{"dead", "working"}) {
		t.Fatalf("got %q %v, attempted %v", got, err, attempted)
	}
}

func TestIOSRelayKeepsSlowPrimaryAsLastResort(t *testing.T) {
	var tried []string
	got, err := tryIOSRelayHashes(context.Background(), []string{"slow", "dead"}, func(_ context.Context, hash string, budget time.Duration) (string, error) {
		tried = append(tried, hash)
		switch len(tried) {
		case 1:
			return "", errIOSRelayConfigTimeout
		case 2:
			return "", errors.New("reserve unavailable")
		default:
			if budget != 15*time.Second {
				t.Fatalf("slow relay fallback budget %s", budget)
			}
			return "valid config", nil
		}
	})
	if err != nil || got != "valid config" || !reflect.DeepEqual(tried, []string{"slow", "dead", "slow"}) {
		t.Fatalf("got %q %v, attempted %v", got, err, tried)
	}
}

func TestIOSRelayCanStartOnFourthHash(t *testing.T) {
	var elapsed time.Duration
	value, err := tryIOSRelayHashes(context.Background(), []string{"a", "b", "c", "d"}, func(_ context.Context, hash string, budget time.Duration) (string, error) {
		elapsed += budget
		if hash == "d" {
			return hash, nil
		}
		return "", errIOSRelayConfigTimeout
	})
	if err != nil || value != "d" || elapsed > 38*time.Second {
		t.Fatalf("got %q, %v, total budget %s", value, err, elapsed)
	}
}

func TestIOSRelayOneHashKeepsBootstrapBudget(t *testing.T) {
	_, err := tryIOSRelayHashes(context.Background(), []string{"only"}, func(_ context.Context, _ string, budget time.Duration) (string, error) {
		if budget != 30*time.Second {
			t.Fatalf("single relay startup budget changed to %s", budget)
		}
		return "valid config", nil
	})
	if err != nil {
		t.Fatal(err)
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
