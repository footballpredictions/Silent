package main

const (
	ackPrioMaxBytes = 128
	prioChBuf       = 64
)

func isAckPriority(n int) bool {
	return n > 0 && n <= ackPrioMaxBytes
}

func chunkSizeFor(n int) int {
	switch {
	case n >= 1000:
		return 32
	case n >= 400:
		return 16
	default:
		return 8
	}
}
