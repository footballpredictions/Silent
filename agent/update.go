package main

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"debug/elf"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// The builder sets these for every CPU; an ARMv5 package is never offered to ARMv7.
var packageArch = ""
var packageBuildID = ""

const releaseFeed = "https://silentvpn3.github.io/releases.json"
const maxUpdateSize = 64 << 20
const maxUnpackedSize = 256 << 20

type updateState struct {
	Phase   string `json:"phase"`
	Detail  string `json:"detail,omitempty"`
	Version string `json:"version,omitempty"`
}
type updateOffer struct {
	Version      string `json:"version"`
	Arch         string `json:"arch"`
	Platform     string `json:"platform"`
	Size         int64  `json:"size"`
	UnpackedSize int64  `json:"unpacked_size"`
	SHA256       string `json:"sha256"`
	BuildID      string `json:"build_id"`
}
type packageInfo struct {
	Schema   int    `json:"schema_version"`
	Version  string `json:"version"`
	Arch     string `json:"arch"`
	Platform string `json:"platform"`
	BuildID  string `json:"build_id"`
}

func numericVersion(s string) ([]int, bool) {
	p := strings.Split(s, ".")
	if len(p) != 3 {
		return nil, false
	}
	n := make([]int, 3)
	for i, v := range p {
		if v == "" || len(v) > 8 {
			return nil, false
		}
		for _, c := range v {
			if c < '0' || c > '9' {
				return nil, false
			}
		}
		var err error
		n[i], err = strconv.Atoi(v)
		if err != nil {
			return nil, false
		}
	}
	return n, true
}
func newerVersion(candidate, current string) bool {
	a, ok := numericVersion(candidate)
	if !ok {
		return false
	}
	b, ok := numericVersion(current)
	if !ok {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return a[i] > b[i]
		}
	}
	return false
}
func hashValid(s string) bool {
	b, err := hex.DecodeString(s)
	return err == nil && len(b) == 32 && s == strings.ToLower(s)
}
func (u updateOffer) valid() bool {
	return packageArch != "" && u.Arch == packageArch && u.Platform == "keenetic" && newerVersion(u.Version, version) && u.Size > 0 && u.Size <= maxUpdateSize && u.UnpackedSize > 0 && u.UnpackedSize <= maxUnpackedSize && hashValid(u.SHA256) && hashValid(u.BuildID)
}
func (u updateOffer) downloadURL() string {
	return "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v" + u.Version + "/silent-vpn-keenetic-" + u.Version + "-" + u.Arch + ".tar.gz"
}
func updateLock(path string) string { return filepath.Join(filepath.Dir(path), "update.lock") }
func updateBusy(path string) bool {
	lock := updateLock(path)
	info, err := os.Stat(lock)
	if err != nil {
		return false
	}
	b, _ := os.ReadFile(filepath.Join(lock, "pid"))
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil || pid <= 1 {
		return time.Since(info.ModTime()) < 60*time.Second
	}
	return processAlive(pid)
}
func setUpdateState(path string, state updateState) error {
	b, err := json.Marshal(state)
	if err != nil {
		return err
	}
	return writePrivate(filepath.Join(filepath.Dir(path), "update-state.json"), b)
}
func updateStatus(path string) updateState {
	s := updateState{Phase: "idle"}
	if b, err := os.ReadFile(filepath.Join(filepath.Dir(path), "update-state.json")); err == nil {
		_ = json.Unmarshal(b, &s)
	}
	if !updateBusy(path) {
		switch s.Phase {
		case "queued", "checking", "downloading", "verifying", "installing":
			s = updateState{Phase: "error", Detail: "Обновление прервано. Повторите попытку."}
		}
	}
	return s
}

func fetchUpdate(ctx context.Context, client *http.Client) (updateOffer, error) {
	var offer updateOffer
	req, _ := http.NewRequestWithContext(ctx, "GET", releaseFeed+"?check="+strconv.FormatInt(time.Now().Unix(), 10), nil)
	// Public metadata contains no token. Only the Keenetic slot is considered.
	res, err := client.Do(req)
	if err != nil {
		return offer, err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return offer, fmt.Errorf("Не удалось проверить обновление")
	}
	b, err := io.ReadAll(io.LimitReader(res.Body, 262145))
	if err != nil || len(b) > 262144 {
		return offer, fmt.Errorf("Некорректная метадата")
	}
	var feed struct {
		Keenetic struct {
			Arches map[string]updateOffer `json:"arches"`
		} `json:"keenetic"`
	}
	if json.Unmarshal(b, &feed) != nil {
		return offer, fmt.Errorf("Некорректная метадата")
	}
	offer, exists := feed.Keenetic.Arches[packageArch]
	if !exists {
		return updateOffer{}, nil
	}
	if _, ok := numericVersion(offer.Version); !ok {
		return offer, fmt.Errorf("Некорректная версия обновления")
	}
	if !newerVersion(offer.Version, version) {
		return updateOffer{}, nil
	}
	if !offer.valid() {
		return offer, fmt.Errorf("Несовместимое обновление Keenetic")
	}
	return offer, nil
}
func (a *Agent) checkUpdate(ctx context.Context) updateState {
	if updateBusy(a.path) {
		return updateStatus(a.path)
	}
	offer, err := fetchUpdate(ctx, a.client)
	if err != nil {
		return updateState{Phase: "error", Detail: "Не удалось проверить обновление. Повторите попытку."}
	}
	if offer.Version == "" {
		return updateState{Phase: "current"}
	}
	return updateState{Phase: "available", Version: offer.Version}
}
func (a *Agent) startUpdate() (any, error) {
	a.op.Lock()
	defer a.op.Unlock()
	a.mu.RLock()
	token := a.cfg.Token
	a.mu.RUnlock()
	if token == "" {
		return nil, &apiError{401, json.RawMessage(`{"detail":"Войдите в аккаунт"}`)}
	}
	if updateBusy(a.path) {
		return updateStatus(a.path), nil
	}
	lock := updateLock(a.path)
	if err := os.RemoveAll(lock); err != nil {
		return nil, err
	}
	if err := os.Mkdir(lock, 0700); err != nil {
		return nil, err
	}
	if err := setUpdateState(a.path, updateState{Phase: "queued", Detail: "Подготовка обновления"}); err != nil {
		os.RemoveAll(lock)
		return nil, err
	}
	pid, err := launchUpdate(a.path, a.root)
	if err != nil {
		os.RemoveAll(lock)
		_ = setUpdateState(a.path, updateState{Phase: "error", Detail: "Не удалось запустить обновление"})
		return nil, err
	}
	// The worker writes its own PID and acknowledgement, no parent PID overwrite.
	for i := 0; i < 40; i++ {
		b, _ := os.ReadFile(filepath.Join(lock, "started"))
		if strings.TrimSpace(string(b)) == strconv.Itoa(pid) {
			return updateStatus(a.path), nil
		}
		if !processAlive(pid) {
			return updateStatus(a.path), nil
		}
		time.Sleep(50 * time.Millisecond)
	}
	return updateState{Phase: "queued", Detail: "Подготовка обновления"}, nil
}

type updateEnvironment struct {
	TempBase string
	Service  string
	DiskFree func(string) (uint64, error)
	MemFree  func() (uint64, error)
}

func parseMemoryAvailable(data []byte) (uint64, error) {
	var free uint64
	for _, line := range strings.Split(string(data), "\n") {
		p := strings.Fields(line)
		if len(p) != 3 || p[2] != "kB" {
			continue
		}
		if p[0] != "MemAvailable:" && p[0] != "MemFree:" {
			continue
		}
		n, err := strconv.ParseUint(p[1], 10, 64)
		if err != nil || n > 1<<50 {
			return 0, fmt.Errorf("Некорректная RAM")
		}
		if p[0] == "MemAvailable:" {
			return n * 1024, nil
		}
		free = n * 1024
	}
	// Linux 3.2/3.4 may lack MemAvailable: use the conservative free value.
	if free > 0 {
		return free, nil
	}
	return 0, fmt.Errorf("Не удалось проверить свободную RAM")
}

func runUpdateWorker(path, root string) (err error) {
	lock := updateLock(path)
	defer os.RemoveAll(lock)
	defer func() {
		if err != nil {
			_ = setUpdateState(path, updateState{Phase: "error", Detail: "Обновление не завершено. Проверьте память и состояние службы, затем повторите попытку."})
		}
	}()
	if _, err = os.Stat(lock); err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(lock, "pid"), []byte(strconv.Itoa(os.Getpid())), 0600); err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(lock, "started"), []byte(strconv.Itoa(os.Getpid())), 0600); err != nil {
		return err
	}
	_ = setUpdateState(path, updateState{Phase: "checking", Detail: "Проверка обновления"})
	cfg, err := loadConfig(path)
	if err != nil {
		return err
	}
	if cfg.Token == "" {
		return fmt.Errorf("Нужен аккаунт")
	}
	a := &Agent{cfg: cfg, path: path, root: root, client: newHTTPClient(), run: runCommand}
	a.client.Timeout = 10 * time.Minute
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	check, stop := context.WithTimeout(ctx, 20*time.Second)
	offer, err := fetchUpdate(check, a.client)
	stop()
	if err != nil {
		return err
	}
	if offer.Version == "" {
		return setUpdateState(path, updateState{Phase: "current"})
	}
	return a.applyUpdate(ctx, offer, updateEnvironment{TempBase: "/tmp", Service: "/opt/etc/init.d/S99silent-keenetic", DiskFree: diskFree, MemFree: memoryAvailable})
}

func treeSize(root string) (int64, error) {
	var size int64
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("Ссылка в runtime")
		}
		if !d.IsDir() {
			info, e := d.Info()
			if e != nil {
				return e
			}
			size += info.Size()
		}
		return nil
	})
	return size, err
}
func enoughSpace(env updateEnvironment, path string, bytes int64, ram bool) error {
	if bytes < 0 {
		return fmt.Errorf("Некорректный размер")
	}
	free, err := env.DiskFree(path)
	if err != nil || free < uint64(bytes) {
		return fmt.Errorf("Недостаточно места")
	}
	if ram {
		free, err = env.MemFree()
		if err != nil || free < uint64(bytes) {
			return fmt.Errorf("Недостаточно памяти")
		}
	}
	return nil
}

func (a *Agent) applyUpdate(ctx context.Context, offer updateOffer, env updateEnvironment) (err error) {
	if !offer.valid() {
		return fmt.Errorf("Несовместимый пакет")
	}
	stage, err := os.MkdirTemp(env.TempBase, "svk-update-")
	if err != nil {
		return err
	}
	_ = os.Chmod(stage, 0700)
	paused := false
	// Cleanup must precede reconnect on both success and failure, releasing VPN RAM.
	defer func() {
		cleanErr := os.RemoveAll(stage)
		if err == nil {
			err = cleanErr
		}
		if paused {
			if e := a.run(context.Background(), "/bin/sh", env.Service, "start"); e != nil && err == nil {
				err = e
			}
		}
		if err == nil {
			err = setUpdateState(a.path, updateState{Phase: "done", Version: offer.Version, Detail: "Обновление установлено"})
		}
	}()
	if err = enoughSpace(env, stage, offer.Size+(4<<20), true); err != nil {
		return err
	}
	_ = setUpdateState(a.path, updateState{Phase: "downloading", Version: offer.Version, Detail: "Скачивание обновления"})
	payload := filepath.Join(stage, "package.tar.gz")
	req, _ := http.NewRequestWithContext(ctx, "GET", offer.downloadURL(), nil)
	client := *a.client
	client.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if len(via) > 3 || req.URL.Scheme != "https" || (req.URL.Host != "release-assets.githubusercontent.com" && req.URL.Host != "objects.githubusercontent.com") {
			return fmt.Errorf("Неожиданный адрес загрузки")
		}
		return nil
	}
	res, err := client.Do(req)
	if err != nil {
		return err
	}
	if res.StatusCode != 200 {
		res.Body.Close()
		return fmt.Errorf("Не удалось скачать пакет")
	}
	f, err := os.OpenFile(payload, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		res.Body.Close()
		return err
	}
	hash := sha256.New()
	n, copyErr := io.Copy(io.MultiWriter(f, hash), io.LimitReader(res.Body, offer.Size+1))
	closeErr := f.Close()
	res.Body.Close()
	if copyErr != nil || closeErr != nil || n != offer.Size || hex.EncodeToString(hash.Sum(nil)) != offer.SHA256 {
		return fmt.Errorf("Пакет повреждён")
	}
	_ = setUpdateState(a.path, updateState{Phase: "verifying", Version: offer.Version, Detail: "Проверка пакета"})
	if err = scanPackage(payload, offer, ""); err != nil {
		return err
	}
	backup, err := treeSize(a.root)
	if err != nil {
		return err
	}
	configSize, err := treeSize(filepath.Dir(a.path))
	if err != nil {
		return err
	}
	// Destination + rollback are checked before any running client is stopped.
	if err = enoughSpace(env, a.root, offer.UnpackedSize+(4<<20), false); err != nil {
		return err
	}
	_ = setUpdateState(a.path, updateState{Phase: "installing", Version: offer.Version, Detail: "Установка обновления, VPN временно отключён"})
	paused = true
	if err = a.run(ctx, "/bin/sh", env.Service, "stop"); err != nil {
		return err
	}
	// The compressed payload is already allocated in tmpfs; count it in RAM only.
	need := offer.UnpackedSize + backup + configSize + (8 << 20)
	if err = enoughSpace(env, stage, need, false); err != nil {
		return err
	}
	free, memErr := env.MemFree()
	if memErr != nil || free < uint64(need) {
		return fmt.Errorf("Недостаточно памяти после остановки VPN")
	}
	if err = scanPackage(payload, offer, stage); err != nil {
		return err
	}
	prefix := filepath.Join(stage, "silent-vpn-keenetic-"+offer.Version)
	// Existing configuration, LAN password and reconnect intent stay on the router.
	if err = a.run(ctx, "/bin/sh", filepath.Join(prefix, "install.sh"), "--ota"); err != nil {
		return err
	}
	return nil
}

func scanPackage(path string, offer updateOffer, dest string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	prefix := "silent-vpn-keenetic-" + offer.Version + "/"
	allowed := map[string]bool{"ARCH": true, "PACKAGE.json": true, "VERSION": true, "install.sh": true, "uninstall.sh": true, "README.md": true, "RESEARCH.md": true, "THIRD_PARTY_LICENSES.txt": true, "files/network.sh": true, "files/guard.sh": true, "files/100-silent-keenetic.sh": true, "files/S99silent-keenetic": true, "files/ru-direct.domains": true, "files/ru-vpn.domains": true, "bin/" + offer.Arch + "/silent-keenetic": true, "bin/" + offer.Arch + "/spass": true}
	seen := make(map[string]bool)
	var total int64
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		if !strings.HasPrefix(h.Name, prefix) || h.Typeflag != tar.TypeReg || h.Size < 0 {
			return fmt.Errorf("Небезопасный архив")
		}
		rel := strings.TrimPrefix(h.Name, prefix)
		if !allowed[rel] || seen[rel] || h.Size > maxUnpackedSize || total+h.Size > offer.UnpackedSize || h.Mode&07000 != 0 {
			return fmt.Errorf("Несовместимый архив")
		}
		seen[rel] = true
		total += h.Size
		var head []byte
		if rel == "ARCH" || rel == "VERSION" || rel == "PACKAGE.json" || strings.HasPrefix(rel, "bin/") {
			limit := h.Size
			if limit > 65536 {
				limit = 65536
			}
			head, err = io.ReadAll(io.LimitReader(tr, limit))
			if err != nil {
				return err
			}
			switch rel {
			case "ARCH":
				if string(head) != offer.Arch+"\n" {
					return fmt.Errorf("Неверный CPU")
				}
			case "VERSION":
				if string(head) != offer.Version+"\n" {
					return fmt.Errorf("Неверная версия")
				}
			case "PACKAGE.json":
				var p packageInfo
				if json.Unmarshal(head, &p) != nil || p.Schema != 1 || p.Platform != "keenetic" || p.Arch != offer.Arch || p.Version != offer.Version || p.BuildID != offer.BuildID {
					return fmt.Errorf("Неверная метадата пакета")
				}
			default:
				if err = checkELF(head, offer.Arch); err != nil {
					return err
				}
				if h.Mode&0111 == 0 {
					return fmt.Errorf("Бинарник не исполняемый")
				}
			}
		}
		var output io.Writer = io.Discard
		var file *os.File
		if dest != "" {
			name := filepath.Join(dest, filepath.FromSlash(h.Name))
			if err = os.MkdirAll(filepath.Dir(name), 0700); err != nil {
				return err
			}
			mode := os.FileMode(0600)
			if strings.HasSuffix(rel, ".sh") || strings.HasPrefix(rel, "bin/") || strings.HasSuffix(rel, "S99silent-keenetic") {
				mode = 0700
			}
			file, err = os.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
			if err != nil {
				return err
			}
			output = file
		}
		if _, err = output.Write(head); err == nil {
			_, err = io.Copy(output, tr)
		}
		if file != nil {
			closeErr := file.Close()
			if err == nil {
				err = closeErr
			}
		}
		if err != nil {
			return err
		}
	}
	if total != offer.UnpackedSize || len(seen) != len(allowed) {
		return fmt.Errorf("Неполный пакет")
	}
	// Consume the gzip footer to detect truncation/CRC failure without loading ELF.
	// Python/GNU tar pads records to 20 * 512 bytes; Go tar may leave no padding.
	tail, err := io.ReadAll(io.LimitReader(gz, 10241))
	if err != nil {
		return err
	}
	if len(tail) > 10240 {
		return fmt.Errorf("Лишние данные архива")
	}
	for _, b := range tail {
		if b != 0 {
			return fmt.Errorf("Лишние данные архива")
		}
	}
	return nil
}

// Only headers are kept in memory while the VPN still occupies RAM.
func checkELF(head []byte, arch string) error {
	if len(head) < 64 || string(head[:4]) != "\x7fELF" {
		return fmt.Errorf("Неверный ELF")
	}
	targets := map[string][3]byte{"aarch64": {2, 1, 183}, "armv7": {1, 1, 40}, "armv5": {1, 1, 40}, "mipsel": {1, 1, 8}, "mips": {1, 2, 8}, "x86_64": {2, 1, 62}, "i386": {1, 1, 3}}
	target, ok := targets[arch]
	if !ok || head[4] != target[0] || head[5] != target[1] {
		return fmt.Errorf("Неверная архитектура ELF")
	}
	read := func(b []byte) uint64 {
		var n uint64
		if head[5] == 1 {
			for i := len(b) - 1; i >= 0; i-- {
				n = n<<8 | uint64(b[i])
			}
		} else {
			for _, v := range b {
				n = n<<8 | uint64(v)
			}
		}
		return n
	}
	if read(head[18:20]) != uint64(target[2]) {
		return fmt.Errorf("Неверный CPU ELF")
	}
	offset, size, count := read(head[28:32]), read(head[42:44]), read(head[44:46])
	if head[4] == 2 {
		offset, size, count = read(head[32:40]), read(head[54:56]), read(head[56:58])
	}
	if count == 0 || size < 32 || count > 128 || offset+size*count > uint64(len(head)) {
		return fmt.Errorf("Некорректный ELF")
	}
	for i := uint64(0); i < count; i++ {
		if read(head[offset+i*size:offset+i*size+4]) == uint64(elf.PT_INTERP) {
			return fmt.Errorf("Динамический ELF")
		}
	}
	return nil
}
