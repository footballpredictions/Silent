package main

import "testing"

func TestApplicationIdentityIsPlatformSpecific(t *testing.T) {
	for _, test := range []struct {
		exe, selected, platform string
		want                    bool
	}{
		{"/usr/bin/firefox", "/usr/bin/firefox", "linux", true},
		{"/opt/other/firefox", "/usr/bin/firefox", "linux", false},
		{"/usr/bin/Firefox", "/usr/bin/firefox", "linux", false},
		{"/usr/bin/firefox", "firefox", "linux", true},
		{"/Applications/MAX.app/Contents/MacOS/MAX", "/Applications/MAX.app", "darwin", true},
		{"/Applications/MAX.app-other/Contents/MacOS/MAX", "/Applications/MAX.app", "darwin", false},
		{"C:\\Apps\\Game.exe", "game.exe", "windows", true},
	} {
		if got := matchesApplication(test.exe, test.selected, test.platform); got != test.want {
			t.Errorf("%+v got=%v", test, got)
		}
	}
}

func TestProcSocketOwnershipRequiresExactTupleAndRejectsAmbiguousUDP(t *testing.T) {
	f := flow{Protocol: 6, Local: "127.0.0.1:50000", Remote: "203.0.113.7:443"}
	table := "0: 0100007F:C350 077100CB:01BB 01 0:0 0:0 0 1000 0 12345\n"
	if got := socketInode([]string{table}, f); got != "12345" {
		t.Fatal(got)
	}
	f.Remote = "203.0.113.8:443"
	if socketInode([]string{table}, f) != "" {
		t.Fatal("remote ignored")
	}
	f.Protocol = 17
	udp := "0: 00000000:C350 00000000:0000 07 0:0 0:0 0 1000 0 222\n"
	if socketInode([]string{udp}, f) != "222" {
		t.Fatal("wildcard UDP owner missing")
	}
	if socketInode([]string{udp + "1: 00000000:C350 00000000:0000 07 0:0 0:0 0 1001 0 333\n"}, f) != "" {
		t.Fatal("ambiguous UDP acquired an exemption")
	}
}

func TestMacSocketSnapshotKeepsProcessAndSharedIPIsolation(t *testing.T) {
	f := flow{Protocol: 6, Local: "10.66.0.2:50000", Remote: "203.0.113.7:443"}
	snapshot := "p123\x00\nf8\x00PTCP\x00n10.66.0.2:50000->203.0.113.7:443\x00\np456\x00\nf9\x00PTCP\x00n10.66.0.2:50001->203.0.113.7:443\x00\n"
	if lsofOwner(snapshot, f) != 123 {
		t.Fatal("exact owner missing")
	}
	f.Local = "10.66.0.2:50001"
	if lsofOwner(snapshot, f) != 456 {
		t.Fatal("shared remote IP mixed owners")
	}
	f.Local = "10.66.0.2:50002"
	if lsofOwner(snapshot, f) != 0 {
		t.Fatal("unknown owner escaped")
	}
	f.Protocol = 17
	f.Local = "10.66.0.2:50000"
	ambiguous := "p123\x00\nf8\x00PUDP\x00n*:50000\x00\np456\x00\nf9\x00PUDP\x00n*:50000\x00\n"
	if lsofOwner(ambiguous, f) != 0 {
		t.Fatal("ambiguous UDP acquired an exemption")
	}
}
