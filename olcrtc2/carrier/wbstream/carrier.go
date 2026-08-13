package wbstream

import (
	"context"
	"errors"
	"fmt"
	"strings"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
	"github.com/footballpredictions/Silent/olcrtc2/streamframe"
	lib "github.com/openlibrecommunity/olcrtc/pkg/olcrtc"
)

// Carrier — Phase 3: LiveKit path for WB Stream (mirrors telemost Dial wrapper).
type Carrier struct{}

func New() *Carrier { return &Carrier{} }

func (c *Carrier) Provider() olcrtc2.Provider { return olcrtc2.ProviderWBStream }

func (c *Carrier) Dial(ctx context.Context, session olcrtc2.Session) (olcrtc2.PacketConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	room := normalizeRoomID(session.RoomID)
	if room == "" {
		return nil, errors.New("wbstream: empty room id")
	}
	name := "silent-olcrtc2"
	if len(session.CryptoKey) >= 8 {
		name = "o2-" + session.CryptoKey[:8]
	}
	lib.RegisterDefaults()
	sess, err := lib.New(ctx, lib.Config{
		Auth:   "wbstream",
		RoomID: room,
		Name:   name,
		Token:  session.Token,
	})
	if err != nil {
		return nil, fmt.Errorf("wbstream session: %w", err)
	}
	conn, err := sess.Dial(ctx)
	if err != nil {
		_ = sess.Close()
		return nil, fmt.Errorf("wbstream dial: %w", err)
	}
	return streamframe.Wrap(conn), nil
}

func (c *Carrier) Close() error { return nil }

func normalizeRoomID(room string) string {
	room = strings.TrimSpace(room)
	prefixes := []string{
		"https://stream.wb.ru/room/",
		"http://stream.wb.ru/room/",
		"https://stream.wb.ru/",
		"http://stream.wb.ru/",
	}
	for _, p := range prefixes {
		if strings.HasPrefix(room, p) {
			return strings.Trim(strings.TrimPrefix(room, p), "/")
		}
	}
	return room
}
