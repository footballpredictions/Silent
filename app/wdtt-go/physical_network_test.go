package main

import (
	"errors"
	"net"
	"net/url"
	"strings"
	"testing"
)

type fixtureRawSocket uintptr

func (r fixtureRawSocket) Control(f func(uintptr)) error {
	f(uintptr(r))
	return nil
}
func (r fixtureRawSocket) Read(func(uintptr) bool) error  { return nil }
func (r fixtureRawSocket) Write(func(uintptr) bool) error { return nil }

func TestPhysicalTransportControlsOutboundSocketsOnly(t *testing.T) {
	calls := 0
	dialer := physicalTransportDialer(net.Dialer{}, func(fd uintptr) error {
		if fd != 12 {
			t.Fatalf("wrong socket: %d", fd)
		}
		calls++
		return errors.New("network gone")
	})
	for _, test := range []struct{ network, address string }{
		{"tcp4", "127.0.0.1:9000"},
		{"udp6", "[::1]:53"},
		{"tcp4", "192.0.2.10:443"},
		{"udp4", "192.0.2.11:3478"},
	} {
		if err := dialer.Control(test.network, test.address, fixtureRawSocket(12)); err != nil {
			t.Fatal(err)
		}
	}
	if calls != 2 || physicalTransportDialer(net.Dialer{}, nil).Control != nil {
		t.Fatalf("unexpected socket binding: calls=%d", calls)
	}
}

func TestVKDialFailureLogsNetworkErrorWithoutRequestQuery(t *testing.T) {
	cause := errors.New("dial tcp 192.0.2.10:443: i/o timeout")
	requestErr := &url.Error{Op: "Post", URL: "https://fixture.invalid/?link=sensitive-fixture", Err: cause}
	err := newVKCallsFailure("step1 auth.getAnonymToken", vkCallsFailureNetwork, requestErr)
	if text := describeVKCallsFailure(err); strings.Contains(text, "sensitive-fixture") ||
		!strings.Contains(text, cause.Error()) || !errors.Is(err, cause) {
		t.Fatalf("unexpected error rendering: %s", text)
	}
}
