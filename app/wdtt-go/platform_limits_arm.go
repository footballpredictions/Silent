//go:build android && arm

package main

// armeabi-v7a: меньше воркеров/буферов (стабильность), тайминги ramp-up как на 64-bit.
func platformLimits() (workersPerGroup int, returnChBuf int, handshakeCap int, writeLoops int, workerStaggerMs int, groupHandoffMs int) {
	return 3, 1024, 6, 2, 500, 2000
}
