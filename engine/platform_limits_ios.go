//go:build ios

package main

// A packet tunnel runs in an iOS extension with a separate memory budget.
// Use the same small group size as the low-memory Android client.
func platformLimits() (workersPerGroup int, returnChBuf int, handshakeCap int, writeLoops int, workerStaggerMs int, groupHandoffMs int) {
	return iosWorkerGroupSize, 512, 3, 2, 500, 2000
}
