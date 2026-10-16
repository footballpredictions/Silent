//go:build linux || android

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/crypto/curve25519"
	"golang.org/x/net/dns/dnsmessage"
	"golang.org/x/sys/unix"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

// Run the production entry point, including private stdin ACK and TUN FD passing.
func TestNetworkRecoveryWorker(t *testing.T) {
	path := os.Getenv("SILENT_RECOVERY_TEST_CONFIG")
	if path == "" {
		t.Skip("subprocess fixture")
	}
	if err := run(path); err != nil {
		t.Fatal(err)
	}
}

func TestPhysicalHandoverClosesStaleDirectWithoutReplacingVPN(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	var physical net.IP
	addresses, err := net.InterfaceAddrs()
	if err != nil {
		t.Fatal(err)
	}
	for _, address := range addresses {
		if a, ok := address.(*net.IPNet); ok && a.IP.To4() != nil && !a.IP.IsLoopback() && !a.IP.IsLinkLocalUnicast() {
			physical = a.IP.To4()
			break
		}
	}
	if physical == nil {
		t.Fatal("physical IPv4 required")
	}
	listener, err := net.Listen("tcp4", "0.0.0.0:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	var generation atomic.Int32
	dropped := make(chan struct{}, 1)
	go func() {
		for {
			c, err := listener.Accept()
			if err != nil {
				return
			}
			accepted := generation.Load()
			go func() {
				defer c.Close()
				c.SetDeadline(time.Now().Add(15 * time.Second))
				b := make([]byte, 64)
				for {
					n, e := c.Read(b)
					if e != nil {
						return
					}
					if accepted != generation.Load() {
						select {
						case dropped <- struct{}{}:
						default:
						}
						continue // Old carrier/NAT flow is black-holed; new sockets work.
					}
					if _, e = c.Write(b[:n]); e != nil {
						return
					}
				}
			}()
		}
	}()
	hostTun, host, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.2")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	defer hostTun.Close()
	exitTun, exit, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.66.66.1")}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	wg := device.NewDevice(exitTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "fixture: "))
	defer wg.Close()
	a, b := make([]byte, 32), make([]byte, 32)
	rand.Read(a)
	rand.Read(b)
	pubA, _ := curve25519.X25519(a, curve25519.Basepoint)
	pubB, _ := curve25519.X25519(b, curve25519.Basepoint)
	if err := wg.IpcSet(fmt.Sprintf("private_key=%s\nlisten_port=0\npublic_key=%s\nallowed_ip=10.66.66.2/32\n", hex.EncodeToString(b), hex.EncodeToString(pubA))); err != nil {
		t.Fatal(err)
	}
	if err := wg.Up(); err != nil {
		t.Fatal(err)
	}
	state, _ := wg.IpcGet()
	port := ""
	for _, line := range strings.Split(state, "\n") {
		if strings.HasPrefix(line, "listen_port=") {
			port = strings.TrimPrefix(line, "listen_port=")
		}
	}
	dns, err := exit.ListenUDPAddrPort(netip.MustParseAddrPort("10.66.66.1:53"))
	if err != nil {
		t.Fatal(err)
	}
	defer dns.Close()
	go func() {
		buffer := make([]byte, 512)
		for {
			n, address, err := dns.ReadFrom(buffer)
			if err != nil {
				return
			}
			var question dnsmessage.Message
			if question.Unpack(buffer[:n]) != nil || len(question.Questions) != 1 {
				continue
			}
			name := strings.TrimSuffix(question.Questions[0].Name.String(), ".")
			answer := ruFixture(name, true, [4]byte(physical))[28:]
			copy(answer[:2], buffer[:min(n, 2)])
			dns.WriteTo(answer, address)
		}
	}()
	fd, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_DGRAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	parent, child := os.NewFile(uintptr(fd[0]), "host-tun"), os.NewFile(uintptr(fd[1]), "router-tun")
	defer parent.Close()
	defer child.Close()
	go func() {
		for {
			packets, sizes := [][]byte{make([]byte, 65535)}, make([]int, 1)
			if _, err := hostTun.Read(packets, sizes, 0); err != nil {
				return
			}
			if _, err := parent.Write(packets[0][:sizes[0]]); err != nil {
				return
			}
		}
	}()
	go func() {
		packet := make([]byte, 65535)
		for {
			n, e := parent.Read(packet)
			if e != nil {
				return
			}
			if _, e = hostTun.Write([][]byte{packet[:n]}, 0); e != nil {
				return
			}
		}
	}()
	name := fmt.Sprintf("silent-recovery-%d-%d", os.Getpid(), time.Now().UnixNano())
	control, err := net.ListenUnix("unix", &net.UnixAddr{Name: "@" + name, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	control.SetDeadline(time.Now().Add(5 * time.Second))
	cfg := configuration{Socket: name, MTU: 1200, Russian: russianConfig{Direct: []string{"ru"}}, Wireguard: fmt.Sprintf("private_key=%s\npublic_key=%s\nendpoint=127.0.0.1:%s\nallowed_ip=0.0.0.0/0\n", hex.EncodeToString(a), hex.EncodeToString(pubB), port)}
	raw, _ := json.Marshal(cfg)
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	executable, _ := os.Executable()
	cmd := exec.CommandContext(ctx, executable, "-test.run=^TestNetworkRecoveryWorker$")
	cmd.Env = append(os.Environ(), "SILENT_RECOVERY_TEST_CONFIG="+path)
	stdin, _ := cmd.StdinPipe()
	stdout, _ := cmd.StdoutPipe()
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { stdin.Close(); cancel(); cmd.Wait() }()
	connection, err := control.AcceptUnix()
	if err != nil {
		t.Fatalf("FD control: %v, %s", err, stderr.String())
	}
	defer connection.Close()
	if _, _, err := connection.WriteMsgUnix([]byte{1}, unix.UnixRights(int(child.Fd())), nil); err != nil {
		t.Fatal(err)
	}
	lines := make(chan string, 16)
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			lines <- scanner.Text()
		}
		close(lines)
	}()
	wait := func(expected string) {
		t.Helper()
		select {
		case line := <-lines:
			if line != expected {
				t.Fatalf("expected %s, got %s", expected, line)
			}
		case <-ctx.Done():
			t.Fatalf("no %s", expected)
		}
	}
	wait("READY")
	query := func(name string) {
		t.Helper()
		c, e := host.DialUDP(nil, &net.UDPAddr{IP: net.ParseIP("10.66.66.1"), Port: 53})
		if e != nil {
			t.Fatal(e)
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(2 * time.Second))
		c.Write(ruFixture(name, false, [4]byte{})[28:])
		buffer := make([]byte, 512)
		n, e := c.Read(buffer)
		var answer dnsmessage.Message
		if e != nil || answer.Unpack(buffer[:n]) != nil || answer.RCode != dnsmessage.RCodeSuccess || len(answer.Answers) != 1 {
			t.Fatalf("encrypted WG DNS unavailable: %v", e)
		}
	}
	query("probe.ru") // Confirm the encrypted VPN path before resetting physical sockets.
	io.WriteString(stdin, "{\"revision\":1,\"russian\":{\"enabled\":true,\"direct_domains\":[\"ru\"]}}\n")
	wait("POLICY_READY:1")
	address := &net.TCPAddr{IP: physical, Port: listener.Addr().(*net.TCPAddr).Port}
	dial := func() net.Conn {
		t.Helper()
		c, e := host.DialContextTCP(ctx, address)
		if e != nil {
			t.Fatal(e)
		}
		return c
	}
	echo := func(c net.Conn) {
		t.Helper()
		c.SetDeadline(time.Now().Add(2 * time.Second))
		c.Write([]byte("ok"))
		b := make([]byte, 2)
		if _, e := io.ReadFull(c, b); e != nil || string(b) != "ok" {
			t.Fatalf("DIRECT echo: %q %v", b, e)
		}
	}
	old := dial()
	defer old.Close()
	echo(old)
	generation.Add(1)
	old.Write([]byte("lost"))
	select {
	case <-dropped:
	case <-ctx.Done():
		t.Fatal("blackhole not reached")
	}
	io.WriteString(stdin, "{\"revision\":2,\"network_epoch\":1}\n")
	wait("POLICY_READY:2")
	old.SetReadDeadline(time.Now().Add(1200 * time.Millisecond))
	_, err = old.Read(make([]byte, 32))
	if timeout, ok := err.(net.Error); err == nil || ok && timeout.Timeout() {
		t.Fatalf("stale DIRECT socket still hangs after acknowledged handover: %v", err)
	}
	fresh := dial()
	defer fresh.Close()
	echo(fresh)
	io.WriteString(stdin, "{\"revision\":3,\"network_epoch\":1}\n")
	wait("POLICY_READY:3")
	echo(fresh)
	io.WriteString(stdin, "{\"revision\":4,\"targets\":[]}\n")
	wait("POLICY_READY:4")
	echo(fresh)
	query("foreign.test") // The original encrypted WG device/TUN still works.
}
