package main

import (
	"crypto/rand"
	"encoding/base64"
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
	"testing"
	"time"

	"golang.org/x/crypto/curve25519"
	"golang.org/x/net/dns/dnsmessage"
	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

func TestUnixKernelRouting(t *testing.T) {
	if os.Getenv("SILENT_ROUTER_KERNEL") != "isolated" {
		t.Skip("requires isolated PID, mount and network namespaces")
	}
	run := func(args ...string) string {
		t.Helper()
		output, err := exec.Command(args[0], args[1:]...).CombinedOutput()
		if err != nil {
			t.Fatalf("%s: %v: %s", args[0], err, output)
		}
		return string(output)
	}
	run("ip", "link", "set", "lo", "up")
	run("ip", "netns", "add", "ru-wan")
	t.Cleanup(func() { exec.Command("ip", "netns", "del", "ru-wan").Run() })
	run("ip", "link", "add", "wan0", "type", "veth", "peer", "name", "wan-peer")
	run("ip", "link", "set", "wan-peer", "netns", "ru-wan")
	run("ip", "addr", "add", "192.0.2.2/24", "dev", "wan0")
	run("ip", "link", "set", "wan0", "up")
	run("ip", "route", "add", "default", "via", "192.0.2.1")
	run("ip", "-n", "ru-wan", "addr", "add", "192.0.2.1/24", "dev", "wan-peer")
	run("ip", "-n", "ru-wan", "link", "set", "wan-peer", "up")
	run("ip", "-n", "ru-wan", "link", "set", "lo", "up")
	for _, address := range []string{"77.88.8.8", "198.18.0.2", "198.18.0.3", "198.18.0.4"} {
		run("ip", "-n", "ru-wan", "addr", "add", address+"/32", "dev", "lo")
	}
	wanScript := `import socket, threading, struct
def echo():
    server=socket.socket(); server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    server.bind(('0.0.0.0',18080)); server.listen()
    while True:
        client,_=server.accept()
        threading.Thread(target=serve,args=(client,),daemon=True).start()
def serve(client):
    with client:
        while client.recv(1024): client.sendall(b'WAN\n')
threading.Thread(target=echo,daemon=True).start()
server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); server.bind(('77.88.8.8',53))
while True:
    query,peer=server.recvfrom(4096)
    answer=query[:2]+b'\x81\x80'+query[4:6]+b'\x00\x01\x00\x00\x00\x00'+query[12:]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x01\x2c\x00\x04'+socket.inet_aton('198.18.0.2')
    server.sendto(answer,peer)
`
	wan := exec.Command("ip", "netns", "exec", "ru-wan", "python3", "-u", "-c", wanScript)
	if err := wan.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { wan.Process.Kill(); wan.Wait() })
	serverTun, serverNet, err := netstack.CreateNetTUN([]netip.Addr{
		netip.MustParseAddr("10.66.66.1"), netip.MustParseAddr("198.18.0.2"),
		netip.MustParseAddr("198.18.0.3"), netip.MustParseAddr("198.18.0.4"),
		netip.MustParseAddr("1.1.1.1"), netip.MustParseAddr("9.9.9.9"),
	}, nil, 1200)
	if err != nil {
		t.Fatal(err)
	}
	wg := device.NewDevice(serverTun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelSilent, ""))
	defer wg.Close()
	key := func() ([]byte, []byte) {
		private := make([]byte, 32)
		rand.Read(private)
		public, _ := curve25519.X25519(private, curve25519.Basepoint)
		return private, public
	}
	serverKey, serverPublic := key()
	clientKey, clientPublic := key()
	if err = wg.IpcSet("private_key=" + hex.EncodeToString(serverKey) + "\nlisten_port=0\npublic_key=" + hex.EncodeToString(clientPublic) + "\nallowed_ip=10.66.66.2/32\n"); err != nil {
		t.Fatal(err)
	}
	if err = wg.Up(); err != nil {
		t.Fatal(err)
	}
	state, _ := wg.IpcGet()
	port := ""
	for _, line := range strings.Split(state, "\n") {
		if strings.HasPrefix(line, "listen_port=") {
			port = strings.TrimPrefix(line, "listen_port=")
		}
	}
	for _, address := range []string{"198.18.0.2:18080", "198.18.0.3:18080", "198.18.0.4:18080"} {
		listener, err := serverNet.ListenTCPAddrPort(netip.MustParseAddrPort(address))
		if err != nil {
			t.Fatal(err)
		}
		defer listener.Close()
		go func() {
			for {
				client, err := listener.Accept()
				if err != nil {
					return
				}
				go func() {
					defer client.Close()
					buffer := make([]byte, 1024)
					for {
						if _, err := client.Read(buffer); err != nil {
							return
						}
						client.Write([]byte("VPN\n"))
					}
				}()
			}
		}()
	}
	for _, resolver := range []string{"1.1.1.1:53", "9.9.9.9:53"} {
		dns, err := serverNet.ListenUDPAddrPort(netip.MustParseAddrPort(resolver))
		if err != nil {
			t.Fatal(err)
		}
		defer dns.Close()
		go func() {
			buffer := make([]byte, 4096)
			for {
				count, peer, err := dns.ReadFrom(buffer)
				if err != nil {
					return
				}
				var message dnsmessage.Message
				if message.Unpack(buffer[:count]) != nil || len(message.Questions) != 1 {
					continue
				}
				address := [4]byte{198, 18, 0, 3}
				if message.Questions[0].Name.String() == "protected.ru." {
					address[3] = 4
				}
				if message.Questions[0].Name.String() == "shop.ru." {
					address[3] = 2
				}
				message.Response = true
				message.Answers = []dnsmessage.Resource{{Header: dnsmessage.ResourceHeader{Name: message.Questions[0].Name, Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET, TTL: 300}, Body: &dnsmessage.AResource{A: address}}}
				answer, _ := message.Pack()
				dns.WriteTo(answer, peer)
			}
		}()
	}
	configuration := fmt.Sprintf("[Interface]\nPrivateKey = %s\nAddress = 10.66.66.2/32\nMTU = 1200\n[Peer]\nPublicKey = %s\nEndpoint = 127.0.0.1:%s\nAllowedIPs = 0.0.0.0/1, 128.0.0.0/1\nPersistentKeepalive = 25\n", base64.StdEncoding.EncodeToString(clientKey), base64.StdEncoding.EncodeToString(serverPublic), port)
	confPath := filepath.Join(t.TempDir(), "wg-turn.conf")
	if err := os.WriteFile(confPath, []byte(configuration), 0600); err != nil {
		t.Fatal(err)
	}
	helper := os.Getenv("SILENT_ROUTER_HELPER")
	run("python3", helper, "up", confPath, os.Getenv("SILENT_ROUTER_BINARY"))
	pid, err := os.ReadFile("/run/silent-vpn/wireguard-go.pid")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { exec.Command("python3", helper, "down").Run() })
	lookup := func(name string) string {
		t.Helper()
		client, err := net.DialTimeout("udp4", "10.66.66.53:53", time.Second)
		if err != nil {
			t.Fatal(err)
		}
		defer client.Close()
		client.SetDeadline(time.Now().Add(5 * time.Second))
		query := dnsmessage.Message{Header: dnsmessage.Header{ID: 42, RecursionDesired: true}, Questions: []dnsmessage.Question{{Name: dnsmessage.MustNewName(name + "."), Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET}}}
		payload, _ := query.Pack()
		client.Write(payload)
		buffer := make([]byte, 4096)
		count, err := client.Read(buffer)
		if err != nil {
			t.Fatal(err)
		}
		var answer dnsmessage.Message
		if answer.Unpack(buffer[:count]) != nil || len(answer.Answers) == 0 {
			t.Fatal("DNS answer missing")
		}
		return net.IP(answer.Answers[0].Body.(*dnsmessage.AResource).A[:]).String()
	}
	connect := func(address string) net.Conn {
		t.Helper()
		client, err := net.DialTimeout("tcp4", address+":18080", 5*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { client.Close() })
		return client
	}
	check := func(client net.Conn, expected string) {
		t.Helper()
		client.SetDeadline(time.Now().Add(5 * time.Second))
		client.Write([]byte("ping"))
		buffer := make([]byte, 4)
		_, err := io.ReadFull(client, buffer)
		if err != nil || string(buffer) != expected+"\n" {
			t.Fatalf("wanted %s, got %q (%v)", expected, buffer, err)
		}
	}
	policy := func(enabled bool) {
		payload, _ := json.Marshal(policyConfig{Russian: russianConfig{Enabled: enabled, Direct: []string{"ru"}, VPN: []string{"protected.ru"}}, DNS: []string{"9.9.9.9"}})
		run("python3", helper, "russian-policy", string(payload))
	}
	check(connect(lookup("shop.ru")), "VPN")
	policy(true)
	stable := connect(lookup("shop.ru"))
	check(stable, "WAN")
	check(connect(lookup("outside.test")), "VPN")
	check(connect(lookup("protected.ru")), "VPN")
	policy(true)
	check(stable, "WAN")
	policy(false)
	check(connect(lookup("shop.ru")), "VPN")
	policy(true)
	check(connect(lookup("shop.ru")), "WAN")
	after, _ := os.ReadFile("/run/silent-vpn/wireguard-go.pid")
	if string(after) != string(pid) {
		t.Fatal("policy replaced VPN process")
	}
	t.Log("kernel TUN: OFF→VPN, ON→WAN, foreign/override→VPN, identical refresh preserves TCP, OFF/ON without VPN restart")
}
