package main

import (
	"context"
	"log"
	"time"
)

const (
	defaultRampFirstDelay = 50 * time.Second
	defaultRampNextDelay  = 35 * time.Second
	rampFailCascadeDelay  = 3 * time.Second
)

// rampScheduler откладывает старт групп после boot (boot = каскад 2 с, без паузы рампа).
type rampScheduler struct {
	ctx        context.Context
	bootGroups int
	notify     []chan struct{}
	gates      []chan struct{}
	firstDelay time.Duration
	nextDelay  time.Duration
}

// numDelays — число пауз между группами после первой post-boot (numGroups - bootGroups - 1).
func newRampScheduler(ctx context.Context, numDelays, bootGroups int, firstDelay, nextDelay time.Duration) *rampScheduler {
	if numDelays <= 0 {
		return nil
	}
	r := &rampScheduler{
		ctx:        ctx,
		bootGroups: bootGroups,
		notify:     make([]chan struct{}, numDelays),
		gates:      make([]chan struct{}, numDelays),
		firstDelay: firstDelay,
		nextDelay:  nextDelay,
	}
	for i := 0; i < numDelays; i++ {
		r.notify[i] = make(chan struct{}, 1)
		r.gates[i] = make(chan struct{})
		go r.releaseGate(i)
	}
	return r
}

func (r *rampScheduler) releaseGate(idx int) {
	delay := r.nextDelay
	if idx == 0 {
		delay = r.firstDelay
	}
	select {
	case <-r.notify[idx]:
	case <-r.ctx.Done():
		return
	}
	groupNum := r.bootGroups + idx + 2
	log.Printf("[РАМП] Пауза %v перед группой #%d...", delay, groupNum)
	select {
	case <-time.After(delay):
	case <-r.ctx.Done():
		return
	}
	log.Printf("[РАМП] Старт группы #%d (+%d воркеров)", groupNum, workersPerGroup)
	close(r.gates[idx])
}

func (r *rampScheduler) waitForGroup(rampIdx int) <-chan struct{} {
	if rampIdx < 0 || rampIdx >= len(r.gates) {
		ch := make(chan struct{})
		close(ch)
		return ch
	}
	return r.gates[rampIdx]
}

func (r *rampScheduler) passToNext(rampIdx int, success bool) {
	if r == nil || rampIdx < 0 || rampIdx >= len(r.notify) {
		return
	}
	if success {
		log.Printf("[ГРУППА] Успешный старт! Следующая группа по расписанию рампы...")
		select {
		case r.notify[rampIdx] <- struct{}{}:
		default:
		}
		return
	}
	log.Printf("[ГРУППА] Эстафета следующей группе (группа пропущена)")
	go func() {
		time.Sleep(rampFailCascadeDelay)
		close(r.gates[rampIdx])
	}()
}
