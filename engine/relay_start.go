package main

import (
	"context"
	"errors"
	"time"
)

var errIOSRelayConfigTimeout = errors.New("Ретрансляторы не получили конфигурацию VPN вовремя")

const (
	iosMaxWorkers        = 63
	iosMaxWorkersPerHash = 27
	iosBootstrapWorkers  = 3
)

type iosWorkerGroup struct {
	hash    string
	firstID int
	size    int
}

func planIOSWorkerGroups(hashes []string, firstHash string, requested, groupSize int) []iosWorkerGroup {
	if requested <= 0 || groupSize <= 0 || len(hashes) == 0 {
		return nil
	}
	order := []string{firstHash}
	for _, hash := range hashes {
		if hash != firstHash && len(order) < 4 {
			order = append(order, hash)
		}
	}
	target := min(requested, iosMaxWorkers, len(order)*iosMaxWorkersPerHash)
	used := make([]int, len(order))
	var groups []iosWorkerGroup
	for total, index := 0, 0; total < target; index = (index + 1) % len(order) {
		size := min(groupSize, target-total, iosMaxWorkersPerHash-used[index])
		if size == 0 {
			continue
		}
		groups = append(groups, iosWorkerGroup{hash: order[index], firstID: total + 1, size: size})
		total += size
		used[index] += size
	}
	return groups
}

// Use one group during GETCONF. Probe the primary briefly, then use the spare
// hashes within the startup budget.
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
	if err == nil {
		return value, nil
	}
	extra := hashes[2:min(len(hashes), 4)]
	for _, hash := range extra {
		value, err = try(hash, 15*time.Second/time.Duration(len(extra)))
		if err == nil {
			return value, nil
		}
	}
	if len(extra) == 0 && errors.Is(firstErr, errIOSRelayConfigTimeout) {
		return try(hashes[0], 15*time.Second)
	}
	return value, err
}
