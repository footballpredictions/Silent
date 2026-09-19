package main

import (
	"context"
	"sync"
	"time"
)

const allocateMinGap = 100 * time.Millisecond

type allocateGate struct {
	mu   sync.Mutex
	last time.Time
	gap  time.Duration
}

func newAllocateGate() *allocateGate {
	return &allocateGate{gap: allocateMinGap}
}

func (g *allocateGate) Wait(ctx context.Context) error {
	if g == nil {
		return nil
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if !g.last.IsZero() {
		wait := g.gap - time.Since(g.last)
		if wait > 0 {
			timer := time.NewTimer(wait)
			defer timer.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-timer.C:
			}
		}
	}
	g.last = time.Now()
	return nil
}
