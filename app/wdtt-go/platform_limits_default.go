//go:build !android || !arm

package main

func platformLimits() (workersPerGroup int, returnChBuf int, handshakeCap int, writeLoops int, workerStaggerMs int, groupHandoffMs int) {
	// writeLoops 8 как PC 1.0.154; returnCh чуть больше под media bursts.
	return 9, 8192, 40, 8, 500, 2000
}
