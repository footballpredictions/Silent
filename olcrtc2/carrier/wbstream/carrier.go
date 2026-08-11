package wbstream

import (
	"context"
	"errors"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
)

// Carrier — Phase 3: headless Pion / LiveKit path for WB Stream.
// Room create/delete on backend already via HTTP API (ai/olcrtc_wb_api.py).
type Carrier struct{}

func New() *Carrier { return &Carrier{} }

func (c *Carrier) Provider() olcrtc2.Provider { return olcrtc2.ProviderWBStream }

func (c *Carrier) Dial(ctx context.Context, session olcrtc2.Session) (olcrtc2.PacketConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if session.RoomID == "" {
		return nil, errors.New("wbstream: empty room id")
	}
	return nil, errors.New("wbstream: not implemented (Phase 3)")
}

func (c *Carrier) Close() error { return nil }
