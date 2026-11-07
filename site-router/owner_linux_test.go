package main

import (
	"net"
	"os"
	"testing"
)

func TestLinuxActualSocketOwnerHonorsSavedExecutable(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	client, err := net.Dial("tcp4", listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	server, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	f := flow{Protocol: 6, Local: client.LocalAddr().String(), Remote: client.RemoteAddr().String()}
	policy := newProcessPolicy(policyConfig{Excluded: []string{exe}, Russian: russianConfig{Enabled: true}})
	if got := ownerExe(f, policy); got != exe {
		t.Fatalf("actual socket owner=%q want=%q", got, exe)
	}
	policy = newProcessPolicy(policyConfig{Excluded: []string{"/unused/other-app"}, Russian: russianConfig{Enabled: true}})
	if got := ownerExe(f, policy); got != "" {
		t.Fatal("other application acquired this socket", got)
	}
}
