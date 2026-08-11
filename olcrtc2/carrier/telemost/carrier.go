package telemost

import (
	"context"
	"errors"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
)

// Carrier — Phase 2: headless Pion join to Yandex Telemost.
// Stub: returns ErrNotImplemented until Pion wiring lands.
type Carrier struct{}

func New() *Carrier { return &Carrier{} }

func (c *Carrier) Provider() olcrtc2.Provider { return olcrtc2.ProviderTelemost }

func (c *Carrier) Dial(ctx context.Context, session olcrtc2.Session) (olcrtc2.PacketConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if session.RoomID == "" {
		return nil, errors.New("telemost: empty room id")
	}
	return nil, errors.New("telemost: not implemented (Phase 2)")
}

func (c *Carrier) Close() error { return nil }
