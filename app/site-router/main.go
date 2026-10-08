//go:build linux || android

package main

import (
	"bufio"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"sync"
	"syscall"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
)

type configuration struct {
	Socket    string   `json:"socket"`
	Wireguard string   `json:"wireguard"`
	MTU       int      `json:"mtu"`
	Whitelist bool     `json:"whitelist"`
	Targets   []string `json:"targets"`
	Domains   []string `json:"domains"`
	Browsers  []int    `json:"browsers"`
	Debug     bool     `json:"debug"`
}
type cachedRoute struct {
	direct  bool
	expires time.Time
}
type fragmentKey struct {
	Source      [4]byte
	Destination [4]byte
	ID          uint16
	Protocol    byte
}
type routedTun struct {
	file      *os.File
	events    chan tun.Event
	policy    *sitePolicy
	direct    *directStack
	control   *net.UnixConn
	reader    *bufio.Reader
	routes    map[flow]cachedRoute
	fragments map[fragmentKey]cachedRoute
	writeMu   sync.Mutex
	closeOnce sync.Once
	mtu       int
	debug     bool
}

func (t *routedTun) choose(f flow, destination []byte) bool {
	remote, _ := netip.ParseAddrPort(f.Remote)
	if remote.IsValid() && remote.Port() == 53 {
		return false
	}
	// A recycled TCP port must not inherit a previous browser's bypass decision.
	h := int(destination[0]&15) * 4
	if f.Protocol == 6 && len(destination) > h+13 && destination[h+13]&0x12 == 0x02 {
		delete(t.routes, f)
	}
	if route, ok := t.routes[f]; ok && time.Now().Before(route.expires) {
		return route.direct
	}
	// Single TUN reader owns the cache/control channel. An unavailable owner never
	// sends an application's traffic outside its VPN.
	t.control.SetDeadline(time.Now().Add(2 * time.Second))
	b, _ := json.Marshal(f)
	uid := -1
	if _, err := t.control.Write(append(b, '\n')); err == nil {
		if line, e := t.reader.ReadBytes('\n'); e == nil {
			json.Unmarshal(line, &uid)
		} else {
			t.control.Close()
		}
	}
	addr, ok := packetDestination(destination)
	direct := ok && t.policy.direct(uid, addr)
	if t.debug {
		owner := "application"
		if t.policy.browsers[uid] {
			owner = "browser"
		} else if uid < 0 {
			owner = "unknown"
		}
		route := "vpn"
		if direct {
			route = "direct"
		}
		fmt.Printf("FLOW owner=%s route=%s\n", owner, route)
	}
	if len(t.routes) > 4096 {
		clear(t.routes)
	}
	ttl := time.Minute
	if f.Protocol == 17 {
		ttl = 2 * time.Second
	}
	t.routes[f] = cachedRoute{direct, time.Now().Add(ttl)}
	return direct
}
func (t *routedTun) File() *os.File           { return t.file }
func (t *routedTun) Name() (string, error)    { return "silent-browser-router", nil }
func (t *routedTun) MTU() (int, error)        { return t.mtu, nil }
func (t *routedTun) BatchSize() int           { return 1 }
func (t *routedTun) Events() <-chan tun.Event { return t.events }
func (t *routedTun) Close() error {
	t.closeOnce.Do(func() { close(t.events); t.file.Close() })
	return nil
}
func (t *routedTun) writePacket(p []byte) error {
	t.writeMu.Lock()
	defer t.writeMu.Unlock()
	_, err := t.file.Write(p)
	return err
}
func (t *routedTun) Read(buffers [][]byte, sizes []int, offset int) (int, error) {
	for {
		n, err := t.file.Read(buffers[0][offset:])
		if err != nil {
			return 0, err
		}
		packet := buffers[0][offset : offset+n]
		f, _, ok := packetFlow(packet)
		direct := false
		if ok {
			direct = t.choose(f, packet)
		}
		if len(packet) >= 20 && packet[0]>>4 == 4 {
			frag := binary.BigEndian.Uint16(packet[6:8])
			if frag&0x3fff != 0 {
				key := fragmentKey{[4]byte(packet[12:16]), [4]byte(packet[16:20]), binary.BigEndian.Uint16(packet[4:6]), packet[9]}
				if frag&0x1fff == 0 {
					if len(t.fragments) > 512 {
						clear(t.fragments)
					}
					t.fragments[key] = cachedRoute{direct, time.Now().Add(30 * time.Second)}
				} else if previous, exists := t.fragments[key]; exists && time.Now().Before(previous.expires) {
					direct = previous.direct
				}
			}
		}
		if direct {
			t.direct.inject(append([]byte(nil), packet...))
			continue
		}
		sizes[0] = n
		return 1, nil
	}
}
func (t *routedTun) Write(buffers [][]byte, offset int) (int, error) {
	for i, b := range buffers {
		t.policy.observeDNS(b[offset:])
		if err := t.writePacket(b[offset:]); err != nil {
			return i, err
		}
	}
	return len(buffers), nil
}

func receiveTun(c *net.UnixConn) (*os.File, error) {
	b := make([]byte, 1)
	oob := make([]byte, 128)
	_, n, _, _, err := c.ReadMsgUnix(b, oob)
	if err != nil {
		return nil, err
	}
	messages, err := syscall.ParseSocketControlMessage(oob[:n])
	if err != nil {
		return nil, err
	}
	for _, m := range messages {
		fds, e := syscall.ParseUnixRights(&m)
		if e == nil && len(fds) > 0 {
			return os.NewFile(uintptr(fds[0]), "vpn-tun"), nil
		}
	}
	return nil, errors.New("TUN descriptor missing")
}
func run(path string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var cfg configuration
	if err = json.Unmarshal(raw, &cfg); err != nil {
		return err
	}
	if cfg.MTU < 576 || cfg.MTU > 9000 {
		return errors.New("invalid MTU")
	}
	control, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: "@" + cfg.Socket, Net: "unix"})
	if err != nil {
		return err
	}
	defer control.Close()
	file, err := receiveTun(control)
	if err != nil {
		return err
	}
	defer file.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	adapter := &routedTun{file: file, events: make(chan tun.Event, 1), policy: newPolicy(cfg.Whitelist, cfg.Targets, cfg.Browsers), control: control, reader: bufio.NewReader(control), routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), mtu: cfg.MTU, debug: cfg.Debug}
	adapter.policy.domains = cfg.Domains
	adapter.direct = newDirectStack(ctx, cfg.MTU, adapter.writePacket)
	wg := device.NewDevice(adapter, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "site-router: "))
	defer wg.Close()
	if err = wg.IpcSet(cfg.Wireguard); err != nil {
		return errors.New("WireGuard config rejected")
	}
	if err = wg.Up(); err != nil {
		return err
	}
	fmt.Println("READY")
	// Kotlin owns lifetime and closes stdin before closing the FD/process.
	_, err = io.Copy(io.Discard, os.Stdin)
	return err
}
func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "configuration path required")
		os.Exit(2)
	}
	if err := run(os.Args[1]); err != nil {
		fmt.Fprintln(os.Stderr, "router stopped:", err)
		os.Exit(1)
	}
}
