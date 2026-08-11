// Package olcrtc2 — WDTT-coexistence WebRTC carrier engine (Telemost / WB Stream).
//
// Design: .cursor/PLAN_OLCRTC2.md
// Never run srv on the WDTT queen until cell isolation is proven.
package olcrtc2

import "context"

// Family is the client bypass family string.
const Family = "olcrtc2"

// Provider identifies the whitelisted call platform.
type Provider string

const (
	ProviderTelemost Provider = "telemost"
	ProviderWBStream Provider = "wbstream"
)

// Session describes one create-on-demand room (VK-like lifecycle).
type Session struct {
	Provider Provider
	RoomID   string
	Token    string // optional account/moderator JWT (WB)
	CryptoKey string // 64 hex shared key
}

// Carrier joins or hosts a room on a platform SFU (headless Pion — no browser).
type Carrier interface {
	Provider() Provider
	// Dial joins the room and returns a bidirectional packet pipe for the tunnel layer.
	Dial(ctx context.Context, session Session) (PacketConn, error)
	Close() error
}

// PacketConn is a datagram-oriented pipe over the call (VP8/DC framed).
type PacketConn interface {
	ReadPacket(ctx context.Context) ([]byte, error)
	WritePacket(ctx context.Context, p []byte) error
	Close() error
}

// EdgeMode is cnc (client SOCKS) or srv (egress).
type EdgeMode string

const (
	ModeCNC EdgeMode = "cnc"
	ModeSRV EdgeMode = "srv"
)
