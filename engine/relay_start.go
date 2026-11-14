package main

import (
	"context"
	"errors"
	"time"
)

const (
	iosWorkerGroupSize   = 3
	iosMaxWorkers        = 63
	iosMaxWorkersPerHash = 27
)

func iosWorkerGroupCount(requested, hashes int) int {
	capacity := min(iosMaxWorkers, iosMaxWorkersPerHash*min(hashes, 4))
	return min(capacity, max(iosWorkerGroupSize, requested)) / iosWorkerGroupSize
}

// Bootstrap one group at a time. Only fill the remaining worker slots after
// GETCONF and WireGuard have succeeded.
func tryIOSRelayHashes[T any](ctx context.Context, hashes []string, start func(context.Context, string, time.Duration) (T, error)) (T, error) {
	var zero T
	last := errors.New("нет доступных хешей ретрансляторов")
	attempts := min(2, len(hashes))
	budget := 30 * time.Second / time.Duration(max(1, attempts))
	for _, hash := range hashes[:attempts] {
		if ctx.Err() != nil {
			return zero, ctx.Err()
		}
		// The live worker group outlives the startup timer on success.
		value, err := start(ctx, hash, budget)
		if err == nil {
			return value, nil
		}
		last = err
	}
	return zero, last
}
