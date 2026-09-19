package main

import "testing"

func TestAckPriorityIsSmallControlPackets(t *testing.T) {
	if !isAckPriority(40) || !isAckPriority(128) {
		t.Fatal("DNS/ACK-sized packets must use the priority lane")
	}
	if isAckPriority(200) || isAckPriority(1200) {
		t.Fatal("data packets must stay on the data chunk path")
	}
}

func TestChunkSizeGrowsWithPayload(t *testing.T) {
	if chunkSizeFor(200) != 8 {
		t.Fatalf("small data chunk want 8, got %d", chunkSizeFor(200))
	}
	if chunkSizeFor(500) != 16 {
		t.Fatalf("medium chunk want 16, got %d", chunkSizeFor(500))
	}
	if chunkSizeFor(1200) != 32 {
		t.Fatalf("bulk chunk want 32, got %d", chunkSizeFor(1200))
	}
}
