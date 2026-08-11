package olcrtc2

import (
	"context"
	"testing"
	"time"
)

func TestMockCarrierDialPair(t *testing.T) {
	c := NewMockCarrier(ProviderTelemost)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	a, b, err := c.DialPair(ctx, Session{Provider: ProviderTelemost, RoomID: "test-room"})
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	defer b.Close()

	go func() {
		_ = a.WritePacket(ctx, []byte("ping"))
	}()
	got, err := b.ReadPacket(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "ping" {
		t.Fatalf("got %q", got)
	}

	if _, _, err := c.DialPair(ctx, Session{}); err == nil {
		t.Fatal("expected empty room error")
	}
}
