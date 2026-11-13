package main

import (
	"encoding/base64"
	"strings"
	"testing"
)

func TestRelayWireGuardConfigUsesServerIssuedIdentity(t *testing.T) {
	private := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("a", 32)))
	public := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("b", 32)))
	conf := "[Interface]\r\nPrivateKey = " + private + "\r\nAddress = 10.66.9.8/32\r\n[Peer]\r\nPublicKey = " + public + "\r\nEndpoint = 198.51.100.7:9000\r\n"
	got, err := parseRelayWireGuardConfig(conf, "34567")
	if err != nil || got.address != "10.66.9.8/32" ||
		!strings.Contains(got.uapi, "private_key="+strings.Repeat("61", 32)+"\n") ||
		!strings.Contains(got.uapi, "public_key="+strings.Repeat("62", 32)+"\n") ||
		!strings.Contains(got.uapi, "endpoint=127.0.0.1:34567\n") {
		t.Fatal("did not apply the WDTT-issued identity to the local dispatcher")
	}
	for _, bad := range []string{"NOCONF", strings.Replace(conf, "/32", "/24", 1), strings.Replace(conf, private, "invalid", 1)} {
		if _, err := parseRelayWireGuardConfig(bad, "34567"); err == nil {
			t.Fatal("accepted missing or invalid WDTT configuration")
		}
	}
}
