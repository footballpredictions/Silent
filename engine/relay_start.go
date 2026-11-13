package main

import (
	"context"
	"errors"
	"time"
)

// An iOS extension can sustain only one group. Give a second hash its own
// attempt after the first group stops; never keep two groups running together.
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
