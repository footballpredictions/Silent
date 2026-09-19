package main

import (
	"context"
	"log"
	"net"
	"runtime/debug"
	"sync"
	"sync/atomic"
	"time"
)

var pktPool = sync.Pool{
	New: func() interface{} {
		return make([]byte, 2048)
	},
}

func getPktBuf(size int) []byte {
	b := pktPool.Get().([]byte)
	if cap(b) < size {
		b = make([]byte, size)
	}
	return b[:size]
}

func putPktBuf(b []byte) {
	if cap(b) < 2048 {
		return
	}
	pktPool.Put(b[:cap(b)])
}

const (
	// Как PC 1.0.154: anti-stall Telegram (паузы mid-flow / превью).
	uploadRetryMs = 50
	chunkSize     = 8
)

type WorkerSlot struct {
	ID     int
	SendCh chan []byte
}

type Dispatcher struct {
	localConn  net.PacketConn
	clientAddr atomic.Pointer[net.Addr]
	workers    atomic.Pointer[[]*WorkerSlot]
	mu         sync.Mutex // Используется только для записи
	rrIndex    int
	rrCount    int
	ReturnCh   chan []byte
	ctx        context.Context
	cancel     context.CancelFunc
	wg         sync.WaitGroup
	stats      *Stats
}

func NewDispatcher(ctx context.Context, localConn net.PacketConn, stats *Stats) *Dispatcher {
	dctx, dcancel := context.WithCancel(ctx)
	d := &Dispatcher{
		localConn: localConn,
		ReturnCh:  make(chan []byte, returnChBufSize),
		ctx:       dctx,
		cancel:    dcancel,
		stats:     stats,
	}
	
	empty := make([]*WorkerSlot, 0)
	d.workers.Store(&empty)

	d.wg.Add(1 + dispatcherWriteLoops)
	go d.readLoop()
	for i := 0; i < dispatcherWriteLoops; i++ {
		go d.writeLoop()
	}
	log.Printf("[ДИСП] profile: chunk=%d writers=%d retry=%dms (Telegram parity PC 1.0.154)", chunkSize, dispatcherWriteLoops, uploadRetryMs)
	return d
}

func (d *Dispatcher) Shutdown() {
	d.cancel()
	_ = d.localConn.Close()
	d.wg.Wait()
}

func (d *Dispatcher) Register(w *WorkerSlot) {
	d.mu.Lock()
	defer d.mu.Unlock()
	oldWorkers := d.workers.Load()
	newWorkers := make([]*WorkerSlot, len(*oldWorkers)+1)
	copy(newWorkers, *oldWorkers)
	newWorkers[len(*oldWorkers)] = w
	d.workers.Store(&newWorkers)
	log.Printf("[ДИСП] Воркер #%d зарегистрирован (всего: %d)", w.ID, len(newWorkers))
}

func (d *Dispatcher) Unregister(slot *WorkerSlot) {
	d.mu.Lock()
	defer d.mu.Unlock()
	oldWorkers := d.workers.Load()
	newWorkers := make([]*WorkerSlot, 0, len(*oldWorkers))
	for _, w := range *oldWorkers {
		if w != slot {
			newWorkers = append(newWorkers, w)
		}
	}
	d.workers.Store(&newWorkers)
	log.Printf("[ДИСП] Воркер #%d отключён (осталось: %d)", slot.ID, len(newWorkers))
}

// readLoop читает WireGuard-пакеты и распределяет по workers chunk'ами.
//
// Логика: отправляем chunkSize подряд пакетов в один worker, потом переходим
// к следующему. Если текущий worker перегружен (канал полный) — немедленно
// ищем свободный worker и начинаем новый chunk на нём. Это гарантирует:
//   - В рамках chunk пакеты идут через один TURN relay → in-order delivery
//   - Между chunks — разные relay → максимальная агрегатная скорость
//   - Нет блокировки, нет буферизации, нет дополнительного latency
func (d *Dispatcher) readLoop() {
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("readLoop.panic", r)
			log.Printf("[FATAL] panic readLoop: %v", r)
			debug.PrintStack()
		}
		d.wg.Done()
	}()

	for {
		if err := d.ctx.Err(); err != nil {
			return
		}

		pkt := getPktBuf(2048)

		n, addr, err := d.localConn.ReadFrom(pkt)
		if err != nil {
			putPktBuf(pkt)
			if d.ctx.Err() != nil {
				return
			}
			time.Sleep(10 * time.Millisecond)
			continue
		}
		pkt = pkt[:n]

		d.clientAddr.Store(&addr)
		d.stats.AddUp(int64(n))

		workersPtr := d.workers.Load()
		if workersPtr == nil || len(*workersPtr) == 0 {
			putPktBuf(pkt)
			continue
		}

		ws := *workersPtr
		nw := len(ws)

		sent := false
		idx := d.rrIndex % nw

		// Пробуем текущий worker (chunk affinity)
		w := ws[idx]
		select {
		case w.SendCh <- pkt:
			sent = true
			d.rrCount++
			if d.rrCount >= chunkSize {
				d.rrIndex = (idx + 1) % nw
				d.rrCount = 0
			}
		default:
			// Текущий worker перегружен — ищем свободный, начинаем новый chunk
			for i := 1; i < nw; i++ {
				altIdx := (idx + i) % nw
				select {
				case ws[altIdx].SendCh <- pkt:
					sent = true
					d.rrIndex = altIdx
					d.rrCount = 1 // первый пакет нового chunk'а уже отправлен
				default:
				}
				if sent {
					break
				}
			}
		}

		if !sent {
			// Как PC: retry по всем воркерам (не только rrIndex) — иначе drop → TCP RTO.
			deadline := time.Now().Add(uploadRetryMs * time.Millisecond)
			for time.Now().Before(deadline) && !sent {
				for i := 0; i < nw && !sent; i++ {
					alt := ws[(idx+i)%nw]
					select {
					case alt.SendCh <- pkt:
						sent = true
						d.rrIndex = (idx + i) % nw
						d.rrCount = 1
					default:
					}
				}
				if sent {
					break
				}
				select {
				case <-d.ctx.Done():
					putPktBuf(pkt)
					return
				case <-time.After(2 * time.Millisecond):
				}
			}
			if !sent {
				d.rrIndex = (idx + 1) % nw
				d.rrCount = 0
				putPktBuf(pkt)
			}
		}
	}
}

func (d *Dispatcher) writeLoop() {
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("writeLoop.panic", r)
			log.Printf("[FATAL] panic writeLoop: %v", r)
			debug.PrintStack()
		}
		d.wg.Done()
	}()

	for {
		select {
		case <-d.ctx.Done():
			return
		case pkt := <-d.ReturnCh:
			addrPtr := d.clientAddr.Load()
			if addrPtr == nil {
				putPktBuf(pkt)
				continue
			}
			addr := *addrPtr
			if _, err := d.localConn.WriteTo(pkt, addr); err != nil {
				if d.ctx.Err() != nil {
					putPktBuf(pkt)
					return
				}
			}
			d.stats.AddDown(int64(len(pkt)))
			putPktBuf(pkt)
		}
	}
}
