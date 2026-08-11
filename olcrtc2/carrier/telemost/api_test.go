package telemost

import (
	"context"
	"testing"
	"time"
)

func TestNormalizeRoomURL(t *testing.T) {
	if got := NormalizeRoomURL("12345"); got != "https://telemost.yandex.ru/j/12345" {
		t.Fatal(got)
	}
	full := "https://telemost.yandex.ru/j/999"
	if got := NormalizeRoomURL(full); got != full {
		t.Fatal(got)
	}
}

func TestGetConnectionInfoRejectsEmpty(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := GetConnectionInfo(ctx, "", "x"); err == nil {
		t.Fatal("expected error")
	}
}

// Live API: dead/invalid room must fail fast with non-nil error (proves HTTP path).
func TestGetConnectionInfoInvalidRoom(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	_, err := GetConnectionInfo(ctx, "00000000000000", "SilentTest")
	if err == nil {
		t.Fatal("expected API error for invalid room")
	}
	t.Log("ok:", err)
}
