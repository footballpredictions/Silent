package main

import (
	"context"
	"crypto/tls"
	"net"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/pion/dtls/v3"
	"github.com/pion/dtls/v3/pkg/crypto/selfsign"
	"github.com/pion/stun/v3"
	"github.com/pion/turn/v5"
)

// An allocated relay whose media path loses DTLS while TURN control stays alive.
type lostMediaConn struct {
	net.PacketConn
	dropped atomic.Int32
}

func (c *lostMediaConn) ReadFrom(buf []byte) (int, net.Addr, error) {
	for {
		n, addr, err := c.PacketConn.ReadFrom(buf)
		if err != nil {
			return n, addr, err
		}
		channelData := n >= 4 && buf[0]&0xc0 == 0x40
		message := &stun.Message{Raw: buf[:n]}
		sendIndication := message.Decode() == nil && message.Type.Method == stun.MethodSend
		if channelData || sendIndication {
			c.dropped.Add(1)
			continue
		}
		return n, addr, nil
	}
}

func TestSessionRetryEscapesAllocatedRelayWithLostDTLS(t *testing.T) {
	for _, wrap := range []bool{false, true} {
		name := "plain"
		if wrap {
			name = "RTP_AEAD"
		}
		t.Run(name, func(t *testing.T) { sessionRelayRetryFixture(t, wrap, 250*time.Millisecond) })
	}
}

func TestSessionChildHandshakeTimeoutRecovery(t *testing.T) {
	if os.Getenv("SILENT_TEST_FULL_HANDSHAKE") != "1" {
		t.Skip("opt-in validation of the unchanged real 30-second DTLS timeout")
	}
	sessionRelayRetryFixture(t, true, 35*time.Second)
}

func sessionRelayRetryFixture(t *testing.T, wrap bool, firstBudget time.Duration) {
	t.Helper()
	local := getLanIPv4()
	if local == nil {
		t.Skip("no physical IPv4 for local TURN fixture")
	}
	listen := func() net.PacketConn {
		c, err := net.ListenPacket("udp4", net.JoinHostPort(local.String(), "0"))
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = c.Close() })
		return c
	}
	bad := &lostMediaConn{PacketConn: listen()}
	good := listen()
	var configs []turn.PacketConnConfig
	for _, conn := range []net.PacketConn{bad, good} {
		configs = append(configs, turn.PacketConnConfig{
			PacketConn:            conn,
			RelayAddressGenerator: &turn.RelayAddressGeneratorStatic{RelayAddress: local, Address: local.String()},
		})
	}
	server, err := turn.NewServer(turn.ServerConfig{
		Realm: "retry.fixture",
		AuthHandler: func(a *turn.RequestAttributes) (string, []byte, bool) {
			return a.Username, turn.GenerateAuthKey(a.Username, a.Realm, "fixture-pass"), true
		},
		PacketConnConfigs: configs,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	cert, err := selfsign.GenerateSelfSigned()
	if err != nil {
		t.Fatal(err)
	}
	peer, err := dtls.Listen("udp4", &net.UDPAddr{IP: local}, &dtls.Config{
		Certificates:         []tls.Certificate{cert},
		ExtendedMasterSecret: dtls.RequireExtendedMasterSecret,
		CipherSuites:         []dtls.CipherSuiteID{dtls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256},
	})
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	go func() {
		conn, acceptErr := peer.Accept()
		if acceptErr == nil {
			defer conn.Close()
			_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
			_, _ = conn.Read(make([]byte, 256))
		}
	}()
	params := &TurnParams{}
	peerAddress := peer.Addr().(*net.UDPAddr)
	if wrap {
		params.WrapKey, err = deriveWrapKey("fixture-wrap-password")
		if err != nil {
			t.Fatal(err)
		}
		peerAddress = wrappedPeerFixture(t, peerAddress, params.WrapKey)
	}
	stats := NewStats()
	d := NewDispatcher(context.Background(), listen(), stats)
	defer d.Shutdown()
	creds := &Credentials{User: "fixture", Pass: "fixture-pass", TurnURLs: []string{
		"turn:" + bad.LocalAddr().String() + "?transport=udp",
		"turn:" + good.LocalAddr().String() + "?transport=udp",
	}}
	// The same worker identity must survive retry; only the selected relay changes.
	first, cancelFirst := context.WithTimeout(context.Background(), firstBudget)
	_, firstErr := RunSession(first, params, peerAddress, d, "0", false, nil, 2, creds, "", "", stats, 0)
	if firstBudget > 30*time.Second && (first.Err() != nil || firstErr == nil || !strings.Contains(firstErr.Error(), "WRAP_AUTH_TIMEOUT")) {
		cancelFirst()
		t.Fatalf("handshake timeout did not release the worker while its parent stayed active: %v", firstErr)
	}
	cancelFirst()
	if firstErr == nil || bad.dropped.Load() == 0 {
		t.Fatalf("fixture did not reproduce lost DTLS after successful Allocate: err=%v dropped=%d", firstErr, bad.dropped.Load())
	}
	second, cancelSecond := context.WithTimeout(context.Background(), 1200*time.Millisecond)
	defer cancelSecond()
	done := make(chan error, 1)
	go func() {
		_, err := RunSession(second, params, peerAddress, d, "0", false, nil, 2, creds, "", "", stats, 1)
		done <- err
	}()
	ready := false
	deadline := time.Now().Add(1000 * time.Millisecond)
	for time.Now().Before(deadline) {
		if slots := *d.workers.Load(); len(slots) == 1 && slots[0].ID == 2 {
			ready = true
			break
		}
		time.Sleep(time.Millisecond)
	}
	cancelSecond()
	<-done
	if !ready {
		t.Fatal("retry stayed on the same allocated relay with lost DTLS; healthy alternate UDP relay was never used")
	}
}

// A real RTP/AEAD gateway in front of the fixture DTLS server, like the deployed peer.
func wrappedPeerFixture(t *testing.T, target *net.UDPAddr, key []byte) *net.UDPAddr {
	t.Helper()
	front, err := net.ListenUDP("udp4", &net.UDPAddr{IP: target.IP})
	if err != nil {
		t.Fatal(err)
	}
	back, err := net.DialUDP("udp4", &net.UDPAddr{IP: target.IP}, target)
	if err != nil {
		front.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { front.Close(); back.Close() })
	var client atomic.Pointer[net.UDPAddr]
	go func() {
		buf, plain := make([]byte, 2048), make([]byte, 2048)
		for {
			n, from, err := front.ReadFromUDP(buf)
			if err != nil {
				return
			}
			n, err = obfsUnwrapPacket(key, buf[:n], plain)
			if err != nil {
				continue
			}
			client.Store(from)
			if _, err = back.Write(plain[:n]); err != nil {
				return
			}
		}
	}()
	go func() {
		buf := make([]byte, 2048)
		config, state := NewObfsConfig(), NewObfsState()
		for {
			n, err := back.Read(buf)
			if err != nil {
				return
			}
			if from := client.Load(); from != nil {
				packet, err := obfsWrapPacket(key, buf[:n], config, state)
				if err != nil {
					return
				}
				if _, err = front.WriteToUDP(packet, from); err != nil {
					return
				}
			}
		}
	}()
	return front.LocalAddr().(*net.UDPAddr)
}
