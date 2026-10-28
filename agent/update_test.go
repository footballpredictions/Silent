package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func updateFixture(t *testing.T, mutate func(map[string][]byte)) ([]byte, updateOffer) {
	t.Helper()
	old := packageArch
	packageArch = "x86_64"
	t.Cleanup(func() { packageArch = old })
	info := packageInfo{Schema: 1, Platform: "keenetic", Arch: "x86_64", Version: "1.0.172", BuildID: strings.Repeat("b", 64)}
	p, _ := json.Marshal(info)
	elf := make([]byte, 128)
	copy(elf, "\x7fELF")
	elf[4] = 2
	elf[5] = 1
	elf[6] = 1
	binary.LittleEndian.PutUint16(elf[18:], 62)
	binary.LittleEndian.PutUint64(elf[32:], 64)
	binary.LittleEndian.PutUint16(elf[54:], 56)
	binary.LittleEndian.PutUint16(elf[56:], 1)
	binary.LittleEndian.PutUint32(elf[64:], 1)
	files := map[string][]byte{"ARCH": []byte("x86_64\n"), "VERSION": []byte("1.0.172\n"), "PACKAGE.json": p, "install.sh": []byte("#!/bin/sh\n"), "uninstall.sh": []byte("#!/bin/sh\n"), "README.md": []byte("readme"), "RESEARCH.md": []byte("research"), "THIRD_PARTY_LICENSES.txt": []byte("license"), "files/network.sh": []byte("network"), "files/guard.sh": []byte("guard"), "files/S99silent-keenetic": []byte("service"), "files/100-silent-keenetic.sh": []byte("hook"), "files/ru-direct.domains": []byte("ru\n"), "files/ru-vpn.domains": []byte("youtube.com\n"), "bin/x86_64/silent-keenetic": elf, "bin/x86_64/spass": elf}
	if mutate != nil {
		mutate(files)
	}
	var out bytes.Buffer
	gz := gzip.NewWriter(&out)
	tf := tar.NewWriter(gz)
	var size int64
	for name, data := range files {
		size += int64(len(data))
		mode := int64(0644)
		if strings.HasPrefix(name, "bin/") {
			mode = 0755
		}
		_ = tf.WriteHeader(&tar.Header{Name: "silent-vpn-keenetic-1.0.172/" + name, Mode: mode, Size: int64(len(data))})
		_, _ = tf.Write(data)
	}
	_ = tf.Close()
	_ = gz.Close()
	sum := sha256.Sum256(out.Bytes())
	return out.Bytes(), updateOffer{Platform: "keenetic", Arch: "x86_64", Version: "1.0.172", BuildID: info.BuildID, Size: int64(out.Len()), UnpackedSize: size, SHA256: hex.EncodeToString(sum[:])}
}
func TestUpdateDownloadsFromPublicReleaseRepository(t *testing.T) {
	u := updateOffer{Version: "1.0.169", Arch: "mipsel"}
	want := "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.169/silent-vpn-keenetic-1.0.169-mipsel.tar.gz"
	if got := u.downloadURL(); got != want {
		t.Fatalf("download URL: got %q, want %q", got, want)
	}
}

func TestUpdateRejectsForeignCPUAndInvalidMetadata(t *testing.T) {
	_, u := updateFixture(t, nil)
	if !u.valid() {
		t.Fatal("valid offer rejected")
	}
	for _, change := range []func(*updateOffer){func(u *updateOffer) { u.Arch = "mipsel" }, func(u *updateOffer) { u.Platform = "openwrt" }, func(u *updateOffer) { u.SHA256 = "none" }, func(u *updateOffer) { u.Version = "1.0.169" }, func(u *updateOffer) { u.Version = "1.0.172;sh" }, func(u *updateOffer) { u.UnpackedSize = maxUnpackedSize + 1 }} {
		bad := u
		change(&bad)
		if bad.valid() {
			t.Fatal("unsafe offer accepted", bad)
		}
	}
	if !newerVersion("1.0.172", "1.0.99") || newerVersion("1.0.9", "1.0.10") {
		t.Fatal("lexical version comparison")
	}
}

func TestMemoryUnitsAndConservativeLegacyKernelFallback(t *testing.T) {
	for _, tt := range []struct {
		data string
		want uint64
	}{
		{"MemFree: 10000 kB\nMemAvailable: 143312 kB\n", 143312 * 1024},
		{"MemFree: 32768 kB\nCached: 80000 kB\n", 32768 * 1024},
	} {
		n, err := parseMemoryAvailable([]byte(tt.data))
		if err != nil || n != tt.want {
			t.Fatal(n, tt.want, err)
		}
	}
	if _, err := parseMemoryAvailable([]byte("MemAvailable: nope kB\n")); err == nil {
		t.Fatal("invalid RAM accepted")
	}
}
func TestUpdateFeedNeverUsesOpenWrtRelease(t *testing.T) {
	_, u := updateFixture(t, nil)
	a := testAgent(t)
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("Authorization") != "" {
			t.Error("token on public feed")
		}
		w := httptest.NewRecorder()
		_, _ = w.Write([]byte(`{"openwrt":{"arches":{"x86_64":{"version":"9.0.0"}}}}`))
		return w.Result(), nil
	})
	offer, err := fetchUpdate(context.Background(), a.client)
	if err != nil || offer.Version != "" {
		t.Fatal(offer, err)
	}
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		w := httptest.NewRecorder()
		_ = json.NewEncoder(w).Encode(map[string]any{"keenetic": map[string]any{"arches": map[string]any{"x86_64": u}}})
		return w.Result(), nil
	})
	offer, err = fetchUpdate(context.Background(), a.client)
	if err != nil || offer.Version != u.Version {
		t.Fatal(offer, err)
	}
}
func TestPackageVerificationAndBoundedExtraction(t *testing.T) {
	for _, tt := range []struct {
		name   string
		mutate func(map[string][]byte)
		valid  bool
	}{
		{"valid", nil, true},
		{"foreign_cpu", func(f map[string][]byte) { f["ARCH"] = []byte("mipsel\n") }, false},
		{"version", func(f map[string][]byte) { f["VERSION"] = []byte("1.0.173\n") }, false},
		{"traversal", func(f map[string][]byte) { f["../../outside"] = []byte("bad") }, false},
		{"extra_binary", func(f map[string][]byte) { f["bin/mipsel/spass"] = []byte("bad") }, false},
		{"missing", func(f map[string][]byte) { delete(f, "files/network.sh") }, false},
		{"dynamic_binary", func(f map[string][]byte) {
			b := append([]byte(nil), f["bin/x86_64/spass"]...)
			binary.LittleEndian.PutUint32(b[64:], 3)
			f["bin/x86_64/spass"] = b
		}, false},
	} {
		t.Run(tt.name, func(t *testing.T) {
			data, u := updateFixture(t, tt.mutate)
			p := filepath.Join(t.TempDir(), "update.tgz")
			_ = os.WriteFile(p, data, 0600)
			err := scanPackage(p, u, "")
			if (err == nil) != tt.valid {
				t.Fatal(err)
			}
			if tt.valid {
				if err = scanPackage(p, u, t.TempDir()); err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}

func TestPackageAllowsStandardTarRecordPaddingOnly(t *testing.T) {
	for _, valid := range []bool{true, false} {
		data, offer := updateFixture(t, nil)
		reader, err := gzip.NewReader(bytes.NewReader(data))
		if err != nil {
			t.Fatal(err)
		}
		raw, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		_ = reader.Close()
		padding := make([]byte, 6144)
		if !valid {
			padding[0] = 1
		}
		var compressed bytes.Buffer
		writer := gzip.NewWriter(&compressed)
		_, _ = writer.Write(append(raw, padding...))
		_ = writer.Close()
		path := filepath.Join(t.TempDir(), "padded.tar.gz")
		_ = os.WriteFile(path, compressed.Bytes(), 0600)
		if err = scanPackage(path, offer, ""); (err == nil) != valid {
			t.Fatal("padding validation", valid, err)
		}
	}
}
func TestUpdateTransactionPreservesVPNUntilVerificationAndCleansBeforeRestart(t *testing.T) {
	for _, scenario := range []string{"success", "bad_sha", "bad_archive", "low_ram", "install_failure"} {
		t.Run(scenario, func(t *testing.T) {
			mutate := func(f map[string][]byte) {}
			if scenario == "bad_archive" {
				mutate = func(f map[string][]byte) { f["../../outside"] = []byte("bad") }
			}
			data, u := updateFixture(t, mutate)
			if scenario == "bad_sha" {
				u.SHA256 = strings.Repeat("a", 64)
			}
			a := testAgent(t)
			a.root = t.TempDir()
			_ = os.WriteFile(filepath.Join(a.root, "silent-keenetic"), []byte("old runtime"), 0600)
			a.cfg.Token = "private-token"
			a.cfg.Reconnect = true
			if err := a.persist(); err != nil {
				t.Fatal(err)
			}
			base := t.TempDir()
			var steps []string
			a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				steps = append(steps, "download")
				if r.Header.Get("Authorization") != "" {
					t.Error("credential on GitHub")
				}
				w := httptest.NewRecorder()
				_, _ = w.Write(data)
				return w.Result(), nil
			})
			a.run = func(ctx context.Context, command string, args ...string) error {
				act := args[len(args)-1]
				steps = append(steps, act)
				if act == "start" {
					entries, _ := os.ReadDir(base)
					if len(entries) != 0 {
						t.Error("payload/rollback retained during reconnect")
					}
				}
				if act == "--ota" && scenario == "install_failure" {
					return fmt.Errorf("installer rolled back")
				}
				return nil
			}
			env := updateEnvironment{TempBase: base, Service: "test-service", DiskFree: func(string) (uint64, error) { return 1 << 30, nil }, MemFree: func() (uint64, error) {
				if scenario == "low_ram" && len(steps) > 1 {
					return 0, nil
				}
				return 1 << 30, nil
			}}
			err := a.applyUpdate(context.Background(), u, env)
			if (err == nil) != (scenario == "success") {
				t.Fatal(err)
			}
			want := []string{"download", "stop", "--ota", "start"}
			if scenario == "bad_sha" || scenario == "bad_archive" {
				want = []string{"download"}
			}
			if scenario == "low_ram" {
				want = []string{"download", "stop", "start"}
			}
			if fmt.Sprint(steps) != fmt.Sprint(want) {
				t.Fatal(steps, want)
			}
			entries, _ := os.ReadDir(base)
			if len(entries) != 0 {
				t.Fatal("stage leaked")
			}
			cfg, err := loadConfig(a.path)
			if err != nil || cfg.Token != "private-token" || !cfg.Reconnect {
				t.Fatal("session/reconnect lost", err)
			}
		})
	}
}
