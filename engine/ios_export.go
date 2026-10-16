//go:build ios

package main

/*
#include <stdlib.h>
typedef void (*packet_cb)(const unsigned char *data, int len);
static void call_output(packet_cb cb, const unsigned char *data, int len) {
	if (cb != 0 && data != 0 && len > 0) {
		cb(data, len);
	}
}
*/
import "C"

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/netip"
	"os"
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
	engineMu     sync.Mutex
	engineCancel context.CancelFunc
	engineDev    *device.Device
	engineTUN    *flowTUN
	outputCb     C.packet_cb
	iosPause     int32
	errStorage   [240]byte
)

func setEngineErr(msg string) {
	b := []byte(msg)
	if len(b) > len(errStorage)-1 {
		b = b[:len(errStorage)-1]
	}
	copy(errStorage[:], b)
	errStorage[len(b)] = 0
}

//export wdtt_engine_linked
func wdtt_engine_linked() C.int { return 1 }

//export wdtt_last_error
func wdtt_last_error() *C.char {
	return (*C.char)(unsafe.Pointer(&errStorage[0]))
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
	engineMu.Lock()
	cancel := engineCancel
	dev := engineDev
	t := engineTUN
	engineCancel = nil
	engineDev = nil
	engineTUN = nil
	engineMu.Unlock()
	if cancel != nil {
		cancel()
	}
	if dev != nil {
		dev.Close()
	}
	if t != nil {
		_ = t.Close()
	}
}

//export wdtt_start
func wdtt_start(
	serverIP *C.char,
	serverPort C.int,
	hashesCSV *C.char,
	password *C.char,
	deviceID *C.char,
	workers C.int,
	privB64 *C.char,
	pubB64 *C.char,
	mtu C.int,
	workDir *C.char,
) C.int {
	wdtt_stop()
	setEngineErr("")

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
		_ = os.Chdir(dir)
		if f, err := os.OpenFile("wdtt.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600); err == nil {
			log.SetOutput(f)
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

	nWorkers := int(workers)
	if nWorkers < workersPerGroup {
		nWorkers = workersPerGroup
	}
	// Расширение iOS режут по памяти: три группы, не 63 воркера телефона.
	if nWorkers > workersPerGroup*3 {
		nWorkers = workersPerGroup * 3
	}
	nWorkers = (nWorkers / workersPerGroup) * workersPerGroup

	peerAddr := fmt.Sprintf("%s:%d", ip, port)
	peer, err := net.ResolveUDPAddr("udp", peerAddr)
	if err != nil {
		setEngineErr(err.Error())
		return 4
	}

	localConn, err := net.ListenPacket("udp", "127.0.0.1:9000")
	if err != nil {
		localConn, err = net.ListenPacket("udp", "127.0.0.1:0")
	}
	if err != nil {
		setEngineErr(err.Error())
		return 5
	}
	if uc, ok := localConn.(*net.UDPConn); ok {
		_ = uc.SetReadBuffer(socketBufSize)
		_ = uc.SetWriteBuffer(socketBufSize)
	}
	_, localPort, _ := net.SplitHostPort(localConn.LocalAddr().String())
	if localPort == "" {
		localPort = "9000"
	}

	ctx, cancel := context.WithCancel(context.Background())
	stopLocal := context.AfterFunc(ctx, func() { _ = localConn.Close() })

	mtuN := int(mtu)
	if mtuN < 1280 {
		mtuN = 1200
	}
	flow := newFlowTUN(mtuN)
	uapi, err := wgUAPI(C.GoString(privB64), C.GoString(pubB64), localPort, mtuN)
	if err != nil {
		cancel()
		stopLocal()
		_ = localConn.Close()
		setEngineErr(err.Error())
		return 6
	}
	logger := device.NewLogger(device.LogLevelError, "[wg] ")
	wgDev := device.NewDevice(flow, conn.NewStdNetBind(), logger)
	if err := wgDev.IpcSet(uapi); err != nil {
		wgDev.Close()
		cancel()
		stopLocal()
		_ = localConn.Close()
		setEngineErr(err.Error())
		return 7
	}
	if err := wgDev.Up(); err != nil {
		wgDev.Close()
		cancel()
		stopLocal()
		_ = localConn.Close()
		setEngineErr(err.Error())
		return 8
	}

	engineMu.Lock()
	engineCancel = cancel
	engineDev = wgDev
	engineTUN = flow
	engineMu.Unlock()

	go runIOSWorkers(ctx, localConn, peer, hashes, wrapKey, devID, pass, nWorkers, localPort)
	log.Printf("[iOS] слушаю 127.0.0.1:%s peer %s workers %d", localPort, peerAddr, nWorkers)
	return 0
}

func runIOSWorkers(
	ctx context.Context,
	localConn net.PacketConn,
	peer *net.UDPAddr,
	hashes []string,
	wrapKey []byte,
	deviceID, password string,
	numW int,
	localPort string,
) {
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("ios.workers", r)
			log.Printf("[FATAL] %v", r)
		}
	}()
	stats := NewStats()
	shutdownCh := make(chan struct{})
	go func() {
		<-ctx.Done()
		close(shutdownCh)
	}()
	go stats.RunLoop(shutdownCh)

	disp := NewDispatcher(ctx, localConn, stats)
	defer disp.Shutdown()

	configCh := make(chan string, 1)
	go func() {
		select {
		case raw, ok := <-configCh:
			if ok && raw != "" {
				log.Printf("[КОНФИГ] GETCONF %d байт", len(raw))
			}
		case <-ctx.Done():
		}
	}()

	tp := &TurnParams{Hashes: hashes, WrapKey: wrapKey}
	numGroups := numW / workersPerGroup
	hashCount := len(hashes)
	if hashCount < 1 {
		hashCount = 1
	}
	var wg sync.WaitGroup
	workerID := 1
	var groupGate chan struct{}
	first := make(chan struct{})
	close(first)
	groupGate = first

	for g := 0; g < numGroups; g++ {
		ids := make([]int, workersPerGroup)
		for i := range ids {
			ids[i] = workerID
			workerID++
		}
		gID := g + 1
		var cc chan<- string
		if g == 0 {
			cc = configCh
		}
		waitReady := groupGate
		var signalNext chan struct{}
		if g < numGroups-1 {
			signalNext = make(chan struct{})
			groupGate = signalNext
		}
		isFirst := g == 0
		hashIdx := g % hashCount
		wg.Add(1)
		safeGo("worker-group", func() {
			defer wg.Done()
			WorkerGroup(ctx, gID, hashIdx, tp, peer, disp, localPort,
				isFirst, cc, ids, &iosPause, deviceID, password, stats, waitReady, signalNext)
		})
	}
	wg.Wait()
	log.Println("[iOS] воркеры остановлены")
}

func wgUAPI(privB64, pubB64, localPort string, mtu int) (string, error) {
	priv, err := keyToHex(privB64)
	if err != nil {
		return "", fmt.Errorf("private key: %w", err)
	}
	pub, err := keyToHex(pubB64)
	if err != nil {
		return "", fmt.Errorf("public key: %w", err)
	}
	_ = mtu
	return fmt.Sprintf(
		"private_key=%s\nlisten_port=0\nreplace_peers=true\npublic_key=%s\nendpoint=127.0.0.1:%s\nallowed_ip=0.0.0.0/0\npersistent_keepalive_interval=25\n",
		priv, pub, localPort,
	), nil
}

func keyToHex(b64 string) (string, error) {
	s := strings.TrimSpace(b64)
	raw, err := base64.StdEncoding.DecodeString(s)
	if err != nil || len(raw) != 32 {
		raw, err = base64.RawStdEncoding.DecodeString(s)
	}
	if err != nil {
		return "", err
	}
	if len(raw) != 32 {
		return "", fmt.Errorf("длина %d", len(raw))
	}
	return hex.EncodeToString(raw), nil
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
