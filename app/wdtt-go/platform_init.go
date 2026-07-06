package main

var (
	workersPerGroup      = 9
	returnChBufSize      = 4096
	dispatcherWriteLoops = 4
	workerStaggerMs      = 500
	groupHandoffMs       = 2000
)

var handshakeSem chan struct{}

func init() {
	wpg, retBuf, hsCap, wl, stagger, handoff := platformLimits()
	workersPerGroup = wpg
	returnChBufSize = retBuf
	dispatcherWriteLoops = wl
	workerStaggerMs = stagger
	groupHandoffMs = handoff
	handshakeSem = make(chan struct{}, hsCap)
}
