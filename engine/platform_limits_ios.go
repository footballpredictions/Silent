//go:build ios

package main

// Match arm64 Android's group size. Keep bounded packet queues in the iOS
// extension and allow handshakes and return traffic to overlap across groups.
func platformLimits() (workersPerGroup int, returnChBuf int, handshakeCap int, writeLoops int, workerStaggerMs int, groupHandoffMs int) {
	return 9, 2048, 12, 4, 500, 2000
}
