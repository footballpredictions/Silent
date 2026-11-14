//go:build ios

package main

/*
#include <stdlib.h>
#include <os/proc.h>
typedef void (*packet_cb)(const unsigned char *data, int len);
typedef void (*journal_cb)(const char *message, int level);
static void call_journal(journal_cb cb, const char *message, int level) {
	if (cb != 0) cb(message, level);
}
static void call_output(packet_cb cb, const unsigned char *data, int len) {
	if (cb != 0 && data != 0 && len > 0) {
		cb(data, len);
	}
}
*/
import "C"

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/netip"
	"os"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"
	"unsafe"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
)

// iOS Network Extension: libclient слушает 127.0.0.1, WireGuard шлёт сюда,
// пакеты utun ходят через wdtt_input / callback. Файл собирается только с -tags ios.

var (
	engineLifeMu  sync.Mutex
	engineMu      sync.Mutex
	engineCancel  context.CancelFunc
	engineDone    <-chan struct{}
	engineDev     *device.Device
	engineAddress string
	engineTUN     *flowTUN
	enginePeer    *device.Peer
	engineRelay   iosRelay
	startCancel   context.CancelFunc
	startEpoch    int64
	outputCb      C.packet_cb
	journalCb     C.journal_cb
	iosPause      int32
	engineError   string
)

func setEngineErr(msg string) {
	engineMu.Lock()
	engineError = msg
	engineMu.Unlock()
}

//export wdtt_engine_linked
func wdtt_engine_linked() C.int { return 1 }

//export wdtt_last_error
func wdtt_last_error() *C.char {
	engineMu.Lock()
	defer engineMu.Unlock()
	return C.CString(engineError)
}

//export wdtt_set_journal
func wdtt_set_journal(cb C.journal_cb) {
	engineMu.Lock()
	journalCb = cb
	engineMu.Unlock()
}

func writeIOSJournal(message string, level int) {
	engineMu.Lock()
	cb := journalCb
	engineMu.Unlock()
	if cb == nil || message == "" {
		return
	}
	value := C.CString(message)
	defer C.free(unsafe.Pointer(value))
	C.call_journal(cb, value, C.int(level))
}

type iosJournalWriter struct{}

func (iosJournalWriter) Write(p []byte) (int, error) {
	if len(p) <= 4096 {
		message, level := relayJournalEvent(string(p))
		writeIOSJournal(message, level)
	}
	return len(p), nil
}

//export wdtt_set_output
func wdtt_set_output(cb C.packet_cb) {
	engineMu.Lock()
	outputCb = cb
	engineMu.Unlock()
}

//export wdtt_input
func wdtt_input(data *C.uchar, n C.int) {
	if data == nil || n <= 0 || n > 65535 {
		return
	}
	buf := C.GoBytes(unsafe.Pointer(data), n)
	engineMu.Lock()
	t := engineTUN
	engineMu.Unlock()
	if t == nil {
		return
	}
	select {
	case <-t.closed:
		return
	case t.in <- buf:
	default:
	}
}

//export wdtt_set_russian_policy
func wdtt_set_russian_policy(raw *C.char) C.int {
	if raw == nil {
		return 1
	}
	var config russianConfig
	if json.Unmarshal([]byte(C.GoString(raw)), &config) != nil {
		return 1
	}
	engineMu.Lock()
	t := engineTUN
	engineMu.Unlock()
	if t == nil {
		return 1
	}
	t.routeMu.Lock()
	defer t.routeMu.Unlock()
	select {
	case <-t.closed:
		return 1
	default:
	}
	before := t.russian.epoch()
	t.russian.update(config)
	if before != t.russian.epoch() {
		clear(t.routes)
	}
	if config.Enabled && t.direct == nil {
		t.direct = newDirectStack(t.ctx, t.mtu, t.output)
	}
	return 0
}

//export wdtt_stop
func wdtt_stop() {
	engineLifeMu.Lock()
	defer engineLifeMu.Unlock()
	stopIOSEngine()
}

//export wdtt_start_epoch
func wdtt_start_epoch() C.longlong {
	engineMu.Lock()
	defer engineMu.Unlock()
	return C.longlong(startEpoch)
}

//export wdtt_interrupt_start
func wdtt_interrupt_start() {
	engineMu.Lock()
	startEpoch++
	if startCancel != nil {
		startCancel()
	}
	engineMu.Unlock()
}

func stopIOSEngine() {
	engineMu.Lock()
	cancel := engineCancel
	done := engineDone
	dev := engineDev
	t := engineTUN
	engineCancel = nil
	engineDone = nil
	engineDev = nil
	enginePeer = nil
	engineRelay = iosRelay{}
	engineAddress = ""
	engineTUN = nil
	engineMu.Unlock()
	if cancel != nil {
		cancel()
	}
	if done != nil {
		<-done
	}
	if dev != nil {
		dev.Close()
	}
	if t != nil {
		_ = t.Close()
	}
	log.SetOutput(io.Discard)
}

//export wdtt_start
func wdtt_start(
	serverIP *C.char,
	serverPort C.int,
	hashesCSV *C.char,
	password *C.char,
	deviceID *C.char,
	workers C.int,
	mtu C.int,
	workDir *C.char,
	epoch C.longlong,
) C.int {
	engineLifeMu.Lock()
	defer engineLifeMu.Unlock()
	stopIOSEngine()
	ctx, cancel := context.WithCancel(context.Background())
	engineMu.Lock()
	if int64(epoch) != startEpoch {
		engineMu.Unlock()
		cancel()
		return 9
	}
	startCancel = cancel
	engineMu.Unlock()
	started := false
	defer func() {
		engineMu.Lock()
		startCancel = nil
		engineMu.Unlock()
		if !started {
			cancel()
		}
	}()
	log.SetOutput(iosJournalWriter{})
	setEngineErr("")
	runtime.GOMAXPROCS(2)
	debug.SetGCPercent(50)
	debug.SetMemoryLimit(24 << 20)
	socketBufSize = 256 << 10

	ip := C.GoString(serverIP)
	pass := C.GoString(password)
	devID := C.GoString(deviceID)
	hashes := ParseHashes(C.GoString(hashesCSV))
	dir := C.GoString(workDir)
	port := int(serverPort)
	if ip == "" || port <= 0 || pass == "" || devID == "" || len(hashes) == 0 {
		setEngineErr("не хватает peer, пароля или хешей")
		return 2
	}
	if dir != "" {
		_ = os.MkdirAll(dir, 0o700)
		if os.Chdir(dir) == nil {
			_ = os.Remove("wdtt.log")
		}
	}

	setupGlobalResolver()
	setAndroidSysDNSServers("")
	SetActiveFingerprint("ios")
	_ = setCaptchaMode("auto")
	_ = setVKAuthMode("vkcalls")

	wrapKey, err := deriveWrapKey(pass)
	if err != nil {
		setEngineErr(err.Error())
		return 3
	}

	peerAddr := net.JoinHostPort(ip, fmt.Sprint(port))
	peer, err := net.ResolveUDPAddr("udp", peerAddr)
	if err != nil {
		setEngineErr(err.Error())
		return 4
	}

	groups := iosWorkerGroupCount(int(workers), len(hashes))
	var attempt int
	relay, configErr := tryIOSRelayHashes(ctx, hashes, func(ctx context.Context, hash string, budget time.Duration) (iosRelay, error) {
		attempt++
		writeIOSJournal(fmt.Sprintf("Ретранслятор №%d · запрос параметров VK · воркеров: %d", attempt, workersPerGroup), 0)
		result, err := startIOSRelay(ctx, peer, hashes[:min(4, len(hashes))], attempt-1, wrapKey, devID, pass, budget, groups)
		if err != nil && ctx.Err() == nil {
			writeIOSJournal(fmt.Sprintf("Ретранслятор №%d · %s", attempt, err), 2)
		}
		return result, err
	})
	if configErr != nil {
		cancel()
		setEngineErr(configErr.Error())
		if errors.Is(configErr, errIOSRelaySocket) {
			return 5
		}
		return 6
	}
	if ctx.Err() != nil {
		<-relay.done
		return 9
	}

	mtuN := int(mtu)
	if mtuN < 1200 {
		mtuN = 1200
	}
	flow := newFlowTUN(mtuN)
	logger := device.NewLogger(device.LogLevelError, "[wg] ")
	wgDev := device.NewDevice(flow, conn.NewStdNetBind(), logger)
	if err := wgDev.IpcSet(relay.config.uapi); err != nil {
		wgDev.Close()
		cancel()
		<-relay.done
		setEngineErr(err.Error())
		return 7
	}
	if err := wgDev.Up(); err != nil {
		wgDev.Close()
		cancel()
		<-relay.done
		setEngineErr(err.Error())
		return 8
	}
	var publicKey device.NoisePublicKey
	_ = publicKey.FromHex(relay.config.publicKey)

	engineMu.Lock()
	engineCancel = cancel
	engineDone = relay.done
	engineDev = wgDev
	engineAddress = relay.config.address
	engineTUN = flow
	enginePeer = wgDev.LookupPeer(publicKey)
	engineRelay = relay
	engineMu.Unlock()
	started = true

	writeIOSJournal("Сетевой модуль WireGuard запущен", 1)
	return 0
}

var errIOSRelaySocket = errors.New("Не удалось открыть локальный сокет VPN")

type iosRelay struct {
	config relayWireGuardConfig
	done   <-chan struct{}
	expand chan struct{}
}

func startIOSRelay(parent context.Context, peer *net.UDPAddr, hashes []string, firstHash int, wrapKey []byte, deviceID, password string, budget time.Duration, groups int) (iosRelay, error) {
	localConn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		return iosRelay{}, errIOSRelaySocket
	}
	_ = localConn.SetReadBuffer(socketBufSize)
	_ = localConn.SetWriteBuffer(socketBufSize)
	localPort := fmt.Sprint(localConn.LocalAddr().(*net.UDPAddr).Port)
	ctx, cancel := context.WithCancel(parent)
	stopLocal := context.AfterFunc(ctx, func() { _ = localConn.Close() })
	configCh := make(chan string, 1)
	credentialFailure := make(chan error, 1)
	done := make(chan struct{})
	primaryDone := make(chan struct{})
	expand := make(chan struct{}, 1)
	go func() {
		defer close(done)
		defer stopLocal()
		defer cancel()
		defer localConn.Close()
		hash := hashes[firstHash]
		// The first group reads the same cached credentials.
		if _, _, _, err := GetCreds(ctx, hash, 100); err != nil {
			select {
			case credentialFailure <- iosCredentialError(err):
			case <-ctx.Done():
			}
			return
		}
		stats := NewStats()
		disp := NewDispatcher(ctx, localConn, stats)
		defer disp.Shutdown()
		statsDone := make(chan struct{})
		go func() {
			defer close(statsDone)
			ticker := time.NewTicker(10 * time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					const mb = 1024.0 * 1024
					up := float64(stats.totalBytesUp.Load()) / mb
					down := float64(stats.totalBytesDown.Load()) / mb
					writeIOSJournal(fmt.Sprintf("Статистика · воркеры: %d/%d · трафик: %.2f МБ (отпр. %.2f · получ. %.2f)",
						len(*disp.workers.Load()), groups*workersPerGroup, up+down, up, down), 0)
				}
			}
		}()
		defer func() { cancel(); <-statsDone }()
		var pool sync.WaitGroup
		launch := func(groupID int, ready chan struct{}, groupDone chan struct{}) {
			pool.Go(func() {
				defer close(groupDone)
				runIOSWorkers(ctx, disp, stats, peer, hashes[(firstHash+groupID-1)%len(hashes)], wrapKey,
					deviceID, password, localPort, configCh, groupID, ready)
			})
		}
		launch(1, nil, primaryDone)
		select {
		case <-ctx.Done():
		case <-expand:
			writeIOSJournal(fmt.Sprintf("Воркеры: %d настроено · до %d на iOS", groups*workersPerGroup, iosMaxWorkers), 0)
			for id := 2; id <= groups; id++ {
				if ctx.Err() != nil {
					break
				}
				if C.os_proc_available_memory() < 24<<20 {
					writeIOSJournal(fmt.Sprintf("Воркеры: %d запущено · достигнут запас памяти iOS", (id-1)*workersPerGroup), 0)
					break
				}
				ready := make(chan struct{})
				groupDone := make(chan struct{})
				launch(id, ready, groupDone)
				select {
				case <-ctx.Done():
				case <-ready:
				case <-groupDone:
				}
			}
		}
		pool.Wait()
	}()
	timer := time.NewTimer(budget)
	defer timer.Stop()
	select {
	case err = <-credentialFailure:
	case raw := <-configCh:
		config, parseErr := parseRelayWireGuardConfig(raw, localPort)
		if parseErr == nil && ctx.Err() == nil {
			return iosRelay{config: config, done: done, expand: expand}, nil
		}
		err = errors.New("Ретранслятор выдал некорректную конфигурацию VPN")
	case <-primaryDone:
		// Prefer a config already delivered before the workers exited.
		select {
		case raw := <-configCh:
			if config, parseErr := parseRelayWireGuardConfig(raw, localPort); parseErr == nil && ctx.Err() == nil {
				return iosRelay{config: config, done: done, expand: expand}, nil
			}
		default:
		}
		err = errors.New("Ретрансляторы завершились до получения конфигурации VPN")
	case <-done:
		select {
		case err = <-credentialFailure:
		default:
			err = errors.New("Ретрансляторы завершились до получения конфигурации VPN")
		}
	case <-timer.C:
		err = errors.New("Ретрансляторы не получили конфигурацию VPN вовремя")
	case <-parent.Done():
		err = parent.Err()
	}
	cancel()
	<-done
	return iosRelay{}, err
}

func iosCredentialError(err error) error {
	if _, unavailable := asCallUnavailableError(err); unavailable {
		return errors.New("VK не подтвердил доступность звонка для ретранслятора")
	}
	if vkCallsIsFlood(err) {
		return errors.New("VK ограничил частоту запросов к ретрансляторам")
	}
	return errors.New("Не удалось получить параметры ретранслятора VK")
}

func runIOSWorkers(
	ctx context.Context,
	disp *Dispatcher,
	stats *Stats,
	peer *net.UDPAddr,
	hash string,
	wrapKey []byte,
	deviceID, password string,
	localPort string,
	configCh chan<- string,
	groupID int,
	ready chan struct{},
) {
	defer func() {
		if r := recover(); r != nil {
			writeIOSJournal("Группа ретрансляторов завершилась с внутренней ошибкой", 2)
		}
	}()
	tp := &TurnParams{Hashes: []string{hash}, WrapKey: wrapKey}
	ids := make([]int, workersPerGroup)
	for i := range ids {
		ids[i] = (groupID-1)*workersPerGroup + i + 1
	}
	WorkerGroup(ctx, groupID, 0, tp, peer, disp, localPort,
		true, configCh, ids, &iosPause, deviceID, password, stats, nil, ready)
}

//export wdtt_expand_workers
func wdtt_expand_workers() {
	engineMu.Lock()
	expand := engineRelay.expand
	engineMu.Unlock()
	if expand != nil {
		select {
		case expand <- struct{}{}:
		default:
		}
	}
}

//export wdtt_assigned_address
func wdtt_assigned_address() *C.char {
	engineMu.Lock()
	defer engineMu.Unlock()
	if engineAddress == "" {
		return nil
	}
	return C.CString(engineAddress)
}

//export wdtt_probe
func wdtt_probe() {
	engineMu.Lock()
	peer := enginePeer
	engineMu.Unlock()
	if peer != nil {
		_ = peer.SendHandshakeInitiation(false)
	}
}

//export wdtt_reset_direct
func wdtt_reset_direct() {
	engineMu.Lock()
	t := engineTUN
	engineMu.Unlock()
	if t != nil {
		t.routeMu.Lock()
		if t.direct != nil {
			t.direct.resetNetwork()
		}
		t.routeMu.Unlock()
	}
}

//export wdtt_handshake_stamp
func wdtt_handshake_stamp() C.longlong {
	return C.longlong(wireGuardStatus("last_handshake_time_sec"))
}

//export wdtt_received_bytes
func wdtt_received_bytes() C.longlong {
	return C.longlong(wireGuardStatus("rx_bytes"))
}

func wireGuardStatus(field string) int64 {
	engineMu.Lock()
	dev := engineDev
	engineMu.Unlock()
	if dev == nil {
		return 0
	}
	status, err := dev.IpcGet()
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(status, "\n") {
		if value, ok := strings.CutPrefix(line, field+"="); ok {
			n, _ := strconv.ParseInt(value, 10, 64)
			return n
		}
	}
	return 0
}

type russianFlow struct {
	direct  bool
	expires time.Time
}

type flowTUN struct {
	routes  map[flow]russianFlow
	ctx     context.Context
	cancel  context.CancelFunc
	routeMu sync.RWMutex
	russian *russianRouter
	direct  *directStack
	mtu     int
	in      chan []byte
	events  chan tun.Event
	closed  chan struct{}
	once    sync.Once
}

func newFlowTUN(mtu int) *flowTUN {
	ctx, cancel := context.WithCancel(context.Background())
	t := &flowTUN{
		mtu: mtu,
		ctx: ctx, cancel: cancel, russian: newRussianRouter(russianConfig{}),
		routes: make(map[flow]russianFlow),
		in:     make(chan []byte, 128),
		events: make(chan tun.Event, 2),
		closed: make(chan struct{}),
	}
	t.events <- tun.EventUp
	return t
}

func (t *flowTUN) File() *os.File           { return nil }
func (t *flowTUN) MTU() (int, error)        { return t.mtu, nil }
func (t *flowTUN) Name() (string, error)    { return "silent", nil }
func (t *flowTUN) Events() <-chan tun.Event { return t.events }
func (t *flowTUN) BatchSize() int           { return 1 }

func (t *flowTUN) Read(bufs [][]byte, sizes []int, offset int) (int, error) {
	for {
		select {
		case <-t.closed:
			return 0, os.ErrClosed
		case pkt := <-t.in:
			if t.russian.handleDNS(t.ctx, pkt, t.output) {
				continue
			}
			if f, dst, ok := packetFlow(pkt); ok && t.russian.enabled() {
				remote, _ := netip.ParseAddrPort(f.Remote)
				if remote.Port() != 53 {
					t.routeMu.Lock()
					h := int(pkt[0]&15) * 4
					if f.Protocol == 6 && len(pkt) > h+13 && pkt[h+13]&0x12 == 2 {
						delete(t.routes, f)
					}
					route, exists := t.routes[f]
					direct := t.russian.direct(dst)
					if exists && time.Now().Before(route.expires) {
						direct = route.direct && !t.russian.mustVPN(dst)
					}
					if len(t.routes) >= 4096 {
						for key, old := range t.routes {
							if time.Now().After(old.expires) {
								delete(t.routes, key)
							}
						}
					}
					if len(t.routes) < 4096 {
						t.routes[f] = russianFlow{direct, time.Now().Add(5 * time.Minute)}
					}
					stack := t.direct
					t.routeMu.Unlock()
					if direct && stack != nil {
						stack.inject(pkt)
						continue
					}
				}
			}
			if len(bufs) == 0 {
				return 0, nil
			}
			n := copy(bufs[0][offset:], pkt)
			if len(sizes) > 0 {
				sizes[0] = n
			}
			return 1, nil
		}
	}
}

func (t *flowTUN) output(packet []byte) error {
	select {
	case <-t.closed:
		return os.ErrClosed
	default:
	}
	engineMu.Lock()
	cb := outputCb
	engineMu.Unlock()
	if cb != nil && len(packet) > 0 {
		C.call_output(cb, (*C.uchar)(unsafe.Pointer(&packet[0])), C.int(len(packet)))
	}
	return nil
}
func (t *flowTUN) Write(bufs [][]byte, offset int) (int, error) {
	for i, buf := range bufs {
		if offset >= len(buf) {
			continue
		}
		packet := buf[offset:]
		t.russian.observe(packet)
		if err := t.output(packet); err != nil {
			return i, err
		}
	}
	return len(bufs), nil
}

func (t *flowTUN) Close() error {
	t.once.Do(func() {
		t.cancel()
		close(t.closed)
		close(t.events)
	})
	return nil
}
