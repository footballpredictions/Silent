package main

import (
	"log"
	"sync/atomic"
	"time"
)

// Stats — atomic.Int64/Int32: на arm32 (armeabi-v7a) int64 после int32 в struct даёт
// «unaligned 64-bit atomic operation» при atomic.AddInt64.
type Stats struct {
	totalBytesUp      atomic.Int64
	totalBytesDown    atomic.Int64
	activeConnections atomic.Int32
}

func NewStats() *Stats {
	return &Stats{}
}

func (s *Stats) AddUp(n int64)   { s.totalBytesUp.Add(n) }
func (s *Stats) AddDown(n int64) { s.totalBytesDown.Add(n) }
func (s *Stats) IncActive()        { s.activeConnections.Add(1) }
func (s *Stats) DecActive()        { s.activeConnections.Add(-1) }

func (s *Stats) RunLoop(shutdown <-chan struct{}) {
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("stats.panic", r)
			log.Printf("[FATAL] panic in stats: %v", r)
		}
	}()
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-shutdown:
			return
		case <-ticker.C:
			active := s.activeConnections.Load()
			up := s.totalBytesUp.Load()
			down := s.totalBytesDown.Load()
			totalMB := float64(up+down) / (1024.0 * 1024.0)

			log.Printf("[СТАТИСТИКА] Активных: %d | Трафик: %.2f МБ", active, totalMB)
		}
	}
}
