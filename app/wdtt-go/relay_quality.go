package main

import (
	"sort"
	"sync"
	"time"
)

const (
	relayProbeFreshFor = 45 * time.Second
	relayRefreshEvery  = time.Second
	relayPenaltyTurns  = 4 // Even a poor path retains one turn in four.
)

// Observes the existing TURN binding transaction, not an end-to-end speed test.
// No additional probes, payloads, reconnects or server protocol are required.
type relayQuality struct {
	mu       sync.Mutex
	sequence uint64
	success  uint32
	failures uint32
	rtt      time.Duration
	last     time.Time
}

type relayObservation struct {
	sequence uint64
	success  uint32
	failures uint32
	rtt      time.Duration
	last     time.Time
}

func (q *relayQuality) observe(elapsed time.Duration, err error, now time.Time) {
	q.mu.Lock()
	defer q.mu.Unlock()
	q.sequence++
	q.last = now
	if err != nil {
		q.failures++
		q.success = 0
		return
	}
	q.failures = 0
	q.success++
	if elapsed <= 0 {
		elapsed = time.Microsecond
	}
	if q.rtt == 0 {
		q.rtt = elapsed
	} else {
		q.rtt = (3*q.rtt + elapsed) / 4
	}
}

func (q *relayQuality) snapshot() relayObservation {
	q.mu.Lock()
	defer q.mu.Unlock()
	return relayObservation{q.sequence, q.success, q.failures, q.rtt, q.last}
}

type relayChoiceState struct {
	sequence  uint64
	bad       uint32
	recovered uint32
	penalized bool
}

// Owned by the dispatcher's reader. Probe writers only update relayQuality.
// Selection remains chunk8 with the existing full-queue fallback and retry.
type relayScheduler struct {
	states      map[*WorkerSlot]*relayChoiceState
	peers       []*WorkerSlot
	lastRefresh time.Time
	cursor      int
	pass        int
}

func (s *relayScheduler) refresh(ws []*WorkerSlot, now time.Time) {
	changed := len(ws) != len(s.peers)
	if !changed {
		for i := range ws {
			if ws[i] != s.peers[i] {
				changed = true
				break
			}
		}
	}
	if !changed && !s.lastRefresh.IsZero() && now.Sub(s.lastRefresh) < relayRefreshEvery {
		return
	}
	s.lastRefresh = now
	s.peers = append(s.peers[:0], ws...)
	observed := make(map[*WorkerSlot]relayObservation, len(ws))
	var delays []time.Duration
	for _, w := range ws {
		if w.quality == nil {
			continue
		}
		o := w.quality.snapshot()
		if o.last.IsZero() || now.Before(o.last) || now.Sub(o.last) > relayProbeFreshFor {
			continue
		}
		observed[w] = o
		if o.success >= 3 && o.failures == 0 {
			delays = append(delays, o.rtt)
		}
	}
	sort.Slice(delays, func(i, j int) bool { return delays[i] < delays[j] })
	var reference time.Duration
	if len(delays) >= 2 {
		reference = delays[(len(delays)-1)/4]
	}
	states := make(map[*WorkerSlot]*relayChoiceState, len(ws))
	for _, w := range ws {
		st := s.states[w]
		if st == nil {
			st = &relayChoiceState{}
		}
		states[w] = st
		o, fresh := observed[w]
		if !fresh {
			// Unknown/stale observations never make a ready path unusable.
			*st = relayChoiceState{}
			continue
		}
		if o.sequence == st.sequence {
			continue // One probe cannot become three votes after repeated refreshes.
		}
		st.sequence = o.sequence
		badDelay := reference > 0 && o.success >= 3 && o.rtt > 4*reference && o.rtt-reference > 150*time.Millisecond
		switch {
		case o.failures >= 3:
			st.penalized = true
			st.bad = 3
			st.recovered = 0
		case badDelay:
			st.bad++
			st.recovered = 0
			if st.bad >= 3 {
				st.penalized = true
			}
		case o.failures == 0 && (reference == 0 || o.rtt <= 2*reference || o.rtt-reference <= 75*time.Millisecond):
			st.bad = 0
			st.recovered++
			if st.recovered >= 3 {
				st.penalized = false
			}
		default:
			st.bad = 0
			st.recovered = 0
		}
	}
	s.states = states // Forget unregistered paths; reconnects cannot grow the map.
	if len(ws) > 0 {
		s.cursor %= len(ws)
	}
}

func (s *relayScheduler) next(ws []*WorkerSlot, fallback int, now time.Time) int {
	if len(ws) == 0 {
		return 0
	}
	s.refresh(ws, now)
	for checked := 0; checked < len(ws)*relayPenaltyTurns; checked++ {
		idx, pass := s.cursor, s.pass
		s.cursor++
		if s.cursor >= len(ws) {
			s.cursor = 0
			s.pass = (s.pass + 1) % relayPenaltyTurns
		}
		if pass == 0 || !s.states[ws[idx]].penalized {
			return idx
		}
	}
	return fallback % len(ws)
}
