// olcrtc2-cnc — SOCKS5 client side joining the same Telemost room as srv.
//
//	OLCRTC2_ROOM=<id> OLCRTC2_KEY=<64hex> OLCRTC2_SOCKS=127.0.0.1:1080 olcrtc2-cnc
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
	key := os.Getenv("OLCRTC2_KEY")
	room := os.Getenv("OLCRTC2_ROOM")
	socks := env("OLCRTC2_SOCKS", "127.0.0.1:1080")
	if key == "" || room == "" {
		fmt.Fprintln(os.Stderr, "OLCRTC2_KEY and OLCRTC2_ROOM required")
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	c := telemost.New()
	dial := func(ctx context.Context) (olcrtc2.PacketConn, error) {
		return c.Dial(ctx, olcrtc2.Session{Provider: olcrtc2.ProviderTelemost, RoomID: room, CryptoKey: key})
	}

	fmt.Printf("olcrtc2-cnc room=%s socks=%s starting…\n", room, socks)
	pair, err := edge.StartCarrierEdge(ctx, olcrtc2.ModeCNC, key, socks, dial)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer pair.Close()
	fmt.Printf("olcrtc2-cnc ready socks=%s\n", pair.SocksAddr)
	<-ctx.Done()
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
