package main

import "testing"

func TestProfileMTU(t *testing.T) {
	for _, tc := range []struct{ recommended, fallback, want int }{
		{1420, 1280, 1420}, {1200, 1420, 1280}, {0, 1280, 1280},
		{-1, 1280, 1280}, {9000, 1280, 1280},
	} {
		if got := profileMTU(tc.recommended, tc.fallback); got != tc.want {
			t.Fatalf("profileMTU(%d, %d) = %d, want %d", tc.recommended, tc.fallback, got, tc.want)
		}
	}
}
