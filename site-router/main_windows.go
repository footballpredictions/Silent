package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
)

type configuration struct {
	Wireguard     string       `json:"wireguard"`
	PhysicalIndex uint32       `json:"physicalIndex"`
	Policy        policyConfig `json:"policy"`
}
type command struct {
	ID     int           `json:"id"`
	Op     string        `json:"op"`
	Policy *policyConfig `json:"policy"`
}
type cachedRoute struct {
	direct  bool
	expires time.Time
}
type fragmentKey struct {
	Source, Destination [4]byte
	ID                  uint16
	Protocol            byte
}
type routedTun struct {
	tun.Device
	policy    atomic.Pointer[processPolicy]
	direct    *directStack
	routes    map[flow]cachedRoute
	fragments map[fragmentKey]cachedRoute
	writeMu   sync.Mutex
	owner     func(flow) string
	routesMu  sync.Mutex
	resetTCP  func(flow) error
}

func (t *routedTun) choose(f flow, packet []byte) bool {
	t.routesMu.Lock()
	defer t.routesMu.Unlock()
	remote, err := netip.ParseAddrPort(f.Remote)
	if err != nil {
		return false
	}
	h := int(packet[0]&15) * 4
	if f.Protocol == 6 && len(packet) > h+13 && packet[h+13]&0x12 == 0x02 {
		delete(t.routes, f)
	}
	if route, ok := t.routes[f]; ok && time.Now().Before(route.expires) {
		return route.direct
	}
	direct := t.policy.Load().direct(t.owner(f), remote.Addr(), remote.Port())
	if len(t.routes) >= 8192 {
		for key, entry := range t.routes {
			if time.Now().After(entry.expires) {
				delete(t.routes, key)
			}
		}
		// Keep live connections stable; new uncached flows still use the current policy.
	}
	ttl := 24 * time.Hour
	if f.Protocol == 17 {
		ttl = 45 * time.Second
	}
	if len(t.routes) < 8192 {
		t.routes[f] = cachedRoute{direct, time.Now().Add(ttl)}
	}
	return direct
}

// Re-evaluate only existing flows whose route actually changed. The tunnel and
// unrelated application/browser connections remain up. TCP clients reconnect on
// the new route after their own TCB is closed; UDP uses the new route immediately.
func (t *routedTun) updatePolicy(cfg policyConfig) int {
	t.routesMu.Lock()
	next := updatedProcessPolicy(t.policy.Load(), cfg)
	t.policy.Store(next)
	changed := make([]flow, 0)
	for f, old := range t.routes {
		if time.Now().After(old.expires) {
			delete(t.routes, f)
			continue
		}
		remote, e := netip.ParseAddrPort(f.Remote)
		if e != nil {
			continue
		}
		if next.direct(t.owner(f), remote.Addr(), remote.Port()) == old.direct {
			continue
		}
		delete(t.routes, f)
		changed = append(changed, f)
	}
	if len(changed) > 0 {
		clear(t.fragments)
	}
	t.routesMu.Unlock()
	for _, f := range changed {
		if t.direct != nil {
			t.direct.closeFlow(f)
		}
		if f.Protocol == 6 && t.resetTCP != nil {
			if err := t.resetTCP(f); err != nil {
				fmt.Fprintln(os.Stderr, "site-router: cannot close changed TCP flow:", err)
			}
		}
	}
	return len(changed)
}

func (t *routedTun) writePacket(p []byte) error {
	t.writeMu.Lock()
	defer t.writeMu.Unlock()
	// NativeTun requires headroom on writes; WireGuard supplies its own on Write.
	b := make([]byte, 16+len(p))
	copy(b[16:], p)
	_, err := t.Device.Write([][]byte{b}, 16)
	return err
}
func (t *routedTun) Read(buffers [][]byte, sizes []int, offset int) (int, error) {
	for {
		n, err := t.Device.Read(buffers, sizes, offset)
		if err != nil {
			return n, err
		}
		if n == 0 {
			continue
		}
		kept := 0
		for i := 0; i < n; i++ {
			packet := buffers[i][offset : offset+sizes[i]]
			f, _, ok := packetFlow(packet)
			direct := false
			if ok {
				direct = t.choose(f, packet)
			}
			if len(packet) >= 20 && packet[0]>>4 == 4 {
				frag := binary.BigEndian.Uint16(packet[6:8])
				if frag&0x3fff != 0 {
					t.routesMu.Lock()
					key := fragmentKey{[4]byte(packet[12:16]), [4]byte(packet[16:20]), binary.BigEndian.Uint16(packet[4:6]), packet[9]}
					if frag&0x1fff == 0 {
						if len(t.fragments) > 512 {
							clear(t.fragments)
						}
						t.fragments[key] = cachedRoute{direct, time.Now().Add(30 * time.Second)}
					} else if old, found := t.fragments[key]; found && time.Now().Before(old.expires) {
						direct = old.direct
					}
					t.routesMu.Unlock()
				}
			}
			if direct {
				t.direct.inject(append([]byte(nil), packet...))
				continue
			}
			if kept != i {
				copy(buffers[kept][offset:], packet)
				sizes[kept] = sizes[i]
			}
			kept++
		}
		if kept > 0 {
			return kept, nil
		}
	}
}
func (t *routedTun) Write(buffers [][]byte, offset int) (int, error) {
	t.writeMu.Lock()
	defer t.writeMu.Unlock()
	for _, b := range buffers {
		t.policy.Load().sites.observeDNS(b[offset:])
	}
	return t.Device.Write(buffers, offset)
}

// Parse wg-quick input, emitting only WireGuard's UAPI. Keys never reach stdout/errors.
func parseConfig(text string) (string, string, int, error) {
	var out strings.Builder
	address := ""
	mtu := 1200
	section := ""
	scanner := bufio.NewScanner(strings.NewReader(text))
	for scanner.Scan() {
		line := strings.TrimSpace(strings.SplitN(scanner.Text(), "#", 2)[0])
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") {
			section = strings.ToLower(line)
			if section == "[peer]" {
				out.WriteString("replace_peers=true\n")
			}
			continue
		}
		fields := strings.SplitN(line, "=", 2)
		if len(fields) != 2 {
			return "", "", 0, errors.New("invalid tunnel configuration")
		}
		key, val := strings.ToLower(strings.TrimSpace(fields[0])), strings.TrimSpace(fields[1])
		switch key {
		case "address":
			for _, s := range strings.Split(val, ",") {
				if a, e := netip.ParsePrefix(strings.TrimSpace(s)); e == nil && a.Addr().Is4() {
					address = a.Addr().String()
				}
			}
		case "mtu":
			if n, e := strconv.Atoi(val); e == nil && n >= 576 && n <= 9000 {
				mtu = n
			}
		case "privatekey", "publickey", "presharedkey":
			b, e := base64.StdEncoding.DecodeString(val)
			if e != nil || len(b) != 32 {
				return "", "", 0, errors.New("invalid tunnel key")
			}
			k := map[string]string{"privatekey": "private_key", "publickey": "public_key", "presharedkey": "preshared_key"}[key]
			out.WriteString(k + "=" + hex.EncodeToString(b) + "\n")
			if key == "publickey" {
				out.WriteString("replace_allowed_ips=true\n")
			}
		case "endpoint":
			a, e := netip.ParseAddrPort(val)
			if e != nil {
				return "", "", 0, errors.New("invalid tunnel endpoint")
			}
			out.WriteString("endpoint=" + a.String() + "\n")
		case "allowedips":
			for _, s := range strings.Split(val, ",") {
				p, e := netip.ParsePrefix(strings.TrimSpace(s))
				if e != nil {
					return "", "", 0, errors.New("invalid tunnel routes")
				}
				out.WriteString("allowed_ip=" + p.String() + "\n")
			}
		case "persistentkeepalive":
			if _, e := strconv.ParseUint(val, 10, 16); e != nil {
				return "", "", 0, e
			}
			out.WriteString("persistent_keepalive_interval=" + val + "\n")
		case "listenport":
			if section == "[interface]" {
				if _, e := strconv.ParseUint(val, 10, 16); e != nil {
					return "", "", 0, e
				}
				out.WriteString("listen_port=" + val + "\n")
			}
		}
	}
	if address == "" {
		return "", "", 0, errors.New("IPv4 tunnel address missing")
	}
	return out.String(), address, mtu, scanner.Err()
}

func run() error {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 2*1024*1024)
	if !scanner.Scan() {
		return errors.New("configuration missing")
	}
	var cfg configuration
	if json.Unmarshal(scanner.Bytes(), &cfg) != nil {
		return errors.New("invalid configuration")
	}
	ipc, address, mtu, err := parseConfig(cfg.Wireguard)
	if err != nil {
		return err
	}
	if cfg.PhysicalIndex == 0 {
		return errors.New("physical interface missing")
	}
	physicalIndex = cfg.PhysicalIndex
	native, err := tun.CreateTUN("wg-turn", mtu)
	if err != nil {
		return err
	}
	adapter := &routedTun{Device: native, routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), resetTCP: resetTCPConnection}
	adapter.policy.Store(newProcessPolicy(cfg.Policy))
	adapter.owner = func(f flow) string { return ownerExe(f, adapter.policy.Load()) }
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	adapter.direct = newDirectStack(ctx, mtu, adapter.writePacket)
	wg := device.NewDevice(adapter, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "site-router: "))
	defer wg.Close()
	if err = wg.IpcSet(ipc); err != nil {
		return errors.New("WireGuard configuration rejected")
	}
	if err = wg.Up(); err != nil {
		return errors.New("WireGuard startup failed")
	}
	enc := json.NewEncoder(os.Stdout)
	enc.Encode(map[string]any{"event": "adapter", "address": address, "mtu": mtu})
	for scanner.Scan() {
		var c command
		if json.Unmarshal(scanner.Bytes(), &c) != nil {
			continue
		}
		switch c.Op {
		case "stop":
			return nil
		case "start":
			enc.Encode(map[string]any{"event": "ready", "id": c.ID, "ok": true})
		case "policy":
			if c.Policy == nil {
				enc.Encode(map[string]any{"id": c.ID, "ok": false})
				continue
			}
			changed := adapter.updatePolicy(*c.Policy)
			enc.Encode(map[string]any{"id": c.ID, "ok": true, "changedFlows": changed})
		}
	}
	return scanner.Err()
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "site-router:", err)
		os.Exit(1)
	}
}
