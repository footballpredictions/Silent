package secure

import (
	"bytes"
	"context"
	"io"
	"testing"
	"time"

	olcrtc2 "github.com/footballpredictions/Silent/olcrtc2"
)

func TestSecureConnRoundTrip(t *testing.T) {
	key, err := ParseKeyHex("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	mock := olcrtc2.NewMockCarrier(olcrtc2.ProviderTelemost)
	a, b, err := mock.DialPair(context.Background(), olcrtc2.Session{RoomID: "sec"})
	if err != nil {
		t.Fatal(err)
	}
	ca, err := Wrap(a, key)
	if err != nil {
		t.Fatal(err)
	}
	cb, err := Wrap(b, key)
	if err != nil {
		t.Fatal(err)
	}
	defer ca.Close()
	defer cb.Close()

	msg := bytes.Repeat([]byte("phase1-"), 200)
	errCh := make(chan error, 1)
	go func() {
		_, err := ca.Write(msg)
		errCh <- err
	}()
	got := make([]byte, len(msg))
	_ = cb.SetReadDeadline(time.Now().Add(3 * time.Second))
	if _, err := io.ReadFull(cb, got); err != nil {
		t.Fatal(err)
	}
	if err := <-errCh; err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, msg) {
		t.Fatalf("mismatch len=%d", len(got))
	}
}
