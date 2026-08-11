package telemost

import (
	"context"
	"errors"
	"fmt"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
	"github.com/footballpredictions/Silent/olcrtc2/carrier/streamframe"
	lib "github.com/openlibrecommunity/olcrtc/pkg/olcrtc"
)

// Carrier joins an existing Telemost room headless via vendor olcrtc (Goolom).
// Create room = separately (Yandex UI / future API). Never run on WDTT queen under load.
type Carrier struct {
	displayName string
}

func New() *Carrier {
	return &Carrier{displayName: "SilentOlcrtc2"}
}

func (c *Carrier) Provider() olcrtc2.Provider { return olcrtc2.ProviderTelemost }

func (c *Carrier) Dial(ctx context.Context, session olcrtc2.Session) (olcrtc2.PacketConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if session.RoomID == "" {
		return nil, errors.New("telemost: empty room id")
	}
	// Preflight: prove Telemost API reachable before WebRTC.
	if _, err := GetConnectionInfo(ctx, session.RoomID, c.displayName); err != nil {
		return nil, fmt.Errorf("telemost preflight: %w", err)
	}

	lib.RegisterDefaults()
	name := c.displayName
	if session.Token != "" {
		name = session.Token // optional display override
	}
	sess, err := lib.New(ctx, lib.Config{
		Auth:   "telemost",
		RoomID: NormalizeRoomURL(session.RoomID),
		Name:   name,
	})
	if err != nil {
		return nil, fmt.Errorf("telemost session: %w", err)
	}
	conn, err := sess.Dial(ctx)
	if err != nil {
		_ = sess.Close()
		return nil, fmt.Errorf("telemost dial: %w", err)
	}
	return streamframe.Wrap(conn), nil
}

func (c *Carrier) Close() error { return nil }
