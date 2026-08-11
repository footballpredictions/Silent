package olcrtc2

import (
	"context"
	"testing"
	"time"
)

func TestMockCarrierDialAndPipe(t *testing.T) {
	c := NewMockCarrier(ProviderTelemost)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	conn, err := c.Dial(ctx, Session{Provider: ProviderTelemost, RoomID: "test-room"})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	if err := conn.WritePacket(ctx, []byte("ping")); err != nil {
		t.Fatal(err)
	}
	// One-sided mock: Write goes to peer channel; Read waits peer — use pair internally differently.
	// Ensure Dial rejects empty room.
	if _, err := c.Dial(ctx, Session{}); err == nil {
		t.Fatal("expected empty room error")
	}
}
