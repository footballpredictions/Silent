//go:build !android || !arm

package main

func platformLimits() (workersPerGroup int, returnChBuf int, handshakeCap int, writeLoops int, workerStaggerMs int, groupHandoffMs int) {
	return 9, 4096, 40, 4, 500, 2000
}
