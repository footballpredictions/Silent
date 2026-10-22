//go:build linux || darwin

package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/ipc"
	"golang.zx2c4.com/wireguard/tun"
)

var physicalIndex uint32

func ownerExe(flow, *processPolicy) string { return "" }
func resetTCPConnection(flow) error        { return errors.New("reset through tunnel") }

func servePolicy(listener net.Listener, adapter *routedTun) {
	for {
		client, err := listener.Accept()
		if err != nil {
			return
		}
		func() {
			defer client.Close()
			client.SetDeadline(time.Now().Add(5 * time.Second))
			var cfg policyConfig
			if json.NewDecoder(io.LimitReader(client, 512*1024)).Decode(&cfg) != nil {
				json.NewEncoder(client).Encode(map[string]any{"ok": false})
				return
			}
			adapter.dnsProxy.update(cfg.DNS)
			changed := adapter.updatePolicy(policyConfig{Russian: cfg.Russian})
			json.NewEncoder(client).Encode(map[string]any{"ok": true, "changedFlows": changed})
		}()
	}
}

func runUnix() error {
	if len(os.Args) != 2 {
		return errors.New("tunnel name required")
	}
	name := os.Args[1]
	if name != "wg-turn" && !(runtime.GOOS == "darwin" && name == "utun") {
		return errors.New("invalid tunnel name")
	}
	iface, err := net.InterfaceByName(os.Getenv("SILENT_LAN_IFACE"))
	if err != nil || iface.Flags&net.FlagLoopback != 0 {
		return errors.New("physical interface required")
	}
	physicalIndex = uint32(iface.Index)
	native, err := tun.CreateTUN(name, 1280)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	adapter := &routedTun{ctx: ctx, Device: native, routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), resetTCP: resetTCPConnection}
	adapter.policy.Store(newProcessPolicy(policyConfig{}))
	adapter.dnsProxy = newTunnelDNS()
	adapter.owner = func(flow) string { return "" }
	adapter.direct = newDirectStack(ctx, 9000, adapter.writePacket)
	wg := device.NewDevice(adapter, conn.NewDefaultBind(), device.NewLogger(device.LogLevelError, "site-router: "))
	defer wg.Close()
	name, err = native.Name()
	if err != nil {
		return err
	}
	uapiFile, err := ipc.UAPIOpen(name)
	if err != nil {
		return err
	}
	defer uapiFile.Close()
	uapi, err := ipc.UAPIListen(name, uapiFile)
	if err != nil {
		return err
	}
	defer uapi.Close()
	policyPath := filepath.Join("/var/run/wireguard", name+".policy.sock")
	os.Remove(policyPath)
	listener, err := net.Listen("unix", policyPath)
	if err != nil {
		return err
	}
	defer os.Remove(policyPath)
	defer listener.Close()
	if err = os.Chmod(policyPath, 0600); err != nil {
		return err
	}
	go servePolicy(listener, adapter)
	acceptErr := make(chan error, 1)
	go func() {
		for {
			client, err := uapi.Accept()
			if err != nil {
				acceptErr <- err
				return
			}
			go wg.IpcHandle(client)
		}
	}()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	defer signal.Stop(signals)
	select {
	case <-signals:
		return nil
	case <-wg.Wait():
		return nil
	case err := <-acceptErr:
		return err
	}
}
