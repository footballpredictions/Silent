// olcrtc2-srv — egress side for Telemost (or mock). Deploy on Hive cell, never on WDTT queen.
//
//	OLCRTC2_MODE=telemost OLCRTC2_ROOM=<id> OLCRTC2_KEY=<64hex> olcrtc2-srv
//	OLCRTC2_MODE=mock OLCRTC2_KEY=<64hex> olcrtc2-srv   # needs paired cnc via separate process — use smoke
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
	"github.com/footballpredictions/Silent/olcrtc2/carrier/telemost"
	"github.com/footballpredictions/Silent/olcrtc2/edge"
)

func main() {
	mode := env("OLCRTC2_MODE", "telemost")
	key := env("OLCRTC2_KEY", "")
	room := env("OLCRTC2_ROOM", "")
	if key == "" {
		fmt.Fprintln(os.Stderr, "OLCRTC2_KEY required (64 hex)")
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	var dial func(context.Context) (olcrtc2.PacketConn, error)
	switch mode {
	case "telemost":
		if room == "" {
			fmt.Fprintln(os.Stderr, "OLCRTC2_ROOM required for telemost")
			os.Exit(2)
		}
		c := telemost.New()
		dial = func(ctx context.Context) (olcrtc2.PacketConn, error) {
			return c.Dial(ctx, olcrtc2.Session{Provider: olcrtc2.ProviderTelemost, RoomID: room, CryptoKey: key})
		}
	default:
		fmt.Fprintf(os.Stderr, "unknown OLCRTC2_MODE=%q (use telemost)\n", mode)
		os.Exit(2)
	}

	fmt.Printf("olcrtc2-srv mode=%s room=%s starting…\n", mode, room)
	pair, err := edge.StartCarrierEdge(ctx, olcrtc2.ModeSRV, key, "", dial)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer pair.Close()
	fmt.Println("olcrtc2-srv ready (egress)")
	<-ctx.Done()
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
