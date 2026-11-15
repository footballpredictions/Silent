package main

import (
	"context"
	"errors"
	"time"
)

var errIOSRelayConfigTimeout = errors.New("Ретрансляторы не получили конфигурацию VPN вовремя")

// Keep one group in memory. With a fallback available, probe the first hash
// briefly and give it a full retry only if the probe timed out and fallback failed.
func tryIOSRelayHashes[T any](ctx context.Context, hashes []string, start func(context.Context, string, time.Duration) (T, error)) (T, error) {
	var zero T
	if err := ctx.Err(); err != nil {
		return zero, err
	}
	switch len(hashes) {
	case 0:
		return zero, errors.New("нет доступных хешей ретрансляторов")
	case 1:
		return start(ctx, hashes[0], 30*time.Second)
	}
	try := func(hash string, budget time.Duration) (T, error) {
		if err := ctx.Err(); err != nil {
			return zero, ctx.Err()
		}
		return start(ctx, hash, budget)
	}
	value, firstErr := try(hashes[0], 8*time.Second)
	if firstErr == nil {
		return value, nil
	}
	value, err := try(hashes[1], 15*time.Second)
	if err != nil && errors.Is(firstErr, errIOSRelayConfigTimeout) {
		return try(hashes[0], 15*time.Second)
	}
	return value, err
}
