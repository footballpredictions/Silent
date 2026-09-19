package main

import (
	"context"
	"testing"
	"time"
)

func TestAllocateGateSpacesSecondCall(t *testing.T) {
	g := newAllocateGate()
	g.gap = 40 * time.Millisecond
	start := time.Now()
	if err := g.Wait(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := g.Wait(context.Background()); err != nil {
		t.Fatal(err)
	}
	elapsed := time.Since(start)
	if elapsed < 40*time.Millisecond {
		t.Fatalf("second Allocate must wait the gap, elapsed %v", elapsed)
	}
}

func TestAllocateGateCancel(t *testing.T) {
	g := newAllocateGate()
	g.gap = time.Second
	if err := g.Wait(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := g.Wait(ctx); err == nil {
		t.Fatal("cancelled wait must return error")
	}
}
