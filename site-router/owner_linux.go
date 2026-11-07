package main

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

type inodeOwner struct{ pid, fd string }

var linuxOwners = struct {
	sync.Mutex
	entries map[string]inodeOwner
}{entries: make(map[string]inodeOwner)}

func linuxApplication(pid string, policy *processPolicy, seen map[string]bool) string {
	for depth := 0; depth < 8 && pid != "" && pid != "0" && !seen[pid]; depth++ {
		seen[pid] = true
		exe, err := os.Readlink(filepath.Join("/proc", pid, "exe"))
		if err == nil && policy.appExcluded(exe) {
			return exe
		}
		data, err := os.ReadFile(filepath.Join("/proc", pid, "stat"))
		if err != nil {
			return ""
		}
		end := strings.LastIndexByte(string(data), ')')
		if end < 0 {
			return ""
		}
		fields := strings.Fields(string(data)[end+1:])
		if len(fields) < 2 {
			return ""
		}
		pid = fields[1]
	}
	return ""
}

func ownerExe(f flow, policy *processPolicy) string {
	if len(policy.excluded) == 0 || (f.Protocol != 6 && f.Protocol != 17) {
		return ""
	}
	table := "tcp"
	if f.Protocol == 17 {
		table = "udp"
	}
	var tables []string
	for _, suffix := range []string{"", "6"} {
		data, _ := os.ReadFile("/proc/net/" + table + suffix)
		tables = append(tables, string(data))
	}
	inode := socketInode(tables, f)
	if inode == "" {
		return ""
	}
	linuxOwners.Lock()
	cached, ok := linuxOwners.entries[inode]
	linuxOwners.Unlock()
	if ok {
		link, _ := os.Readlink(filepath.Join("/proc", cached.pid, "fd", cached.fd))
		if link == "socket:["+inode+"]" {
			return linuxApplication(cached.pid, policy, make(map[string]bool))
		}
	}
	processes, err := os.ReadDir("/proc")
	if err != nil {
		return ""
	}
	deadline := time.Now().Add(150 * time.Millisecond)
	for _, process := range processes {
		if time.Now().After(deadline) {
			return ""
		}
		pid := process.Name()
		if _, err := strconv.Atoi(pid); err != nil {
			continue
		}
		application := linuxApplication(pid, policy, make(map[string]bool))
		if application == "" {
			continue
		}
		fds, err := os.ReadDir(filepath.Join("/proc", pid, "fd"))
		if err != nil {
			continue
		}
		for _, fd := range fds {
			link, _ := os.Readlink(filepath.Join("/proc", pid, "fd", fd.Name()))
			if link != "socket:["+inode+"]" {
				continue
			}
			linuxOwners.Lock()
			if len(linuxOwners.entries) >= 4096 {
				clear(linuxOwners.entries)
			}
			linuxOwners.entries[inode] = inodeOwner{pid, fd.Name()}
			linuxOwners.Unlock()
			return application
		}
	}
	return ""
}

// One bounded OS snapshot serves an entire application-policy edit.
func applicationOwnerSnapshot(policy *processPolicy) func(flow) string {
	index := make(socketOwnerIndex)
	for _, proto := range []struct {
		name   string
		number uint8
	}{{"tcp", 6}, {"udp", 17}} {
		for _, suffix := range []string{"", "6"} {
			data, _ := os.ReadFile("/proc/net/" + proto.name + suffix)
			addProcSockets(index, string(data), proto.number)
		}
	}
	owners := make(map[string]string)
	if len(policy.excluded) > 0 {
		processes, _ := os.ReadDir("/proc")
		deadline := time.Now().Add(150 * time.Millisecond)
		for _, process := range processes {
			if time.Now().After(deadline) {
				break
			}
			pid := process.Name()
			if _, err := strconv.Atoi(pid); err != nil {
				continue
			}
			application := linuxApplication(pid, policy, make(map[string]bool))
			if application == "" {
				continue
			}
			fds, _ := os.ReadDir(filepath.Join("/proc", pid, "fd"))
			for _, fd := range fds {
				link, _ := os.Readlink(filepath.Join("/proc", pid, "fd", fd.Name()))
				if !strings.HasPrefix(link, "socket:[") || !strings.HasSuffix(link, "]") {
					continue
				}
				owners[strings.TrimSuffix(strings.TrimPrefix(link, "socket:["), "]")] = application
			}
		}
	}
	return func(f flow) string { return owners[index.owner(f)] }
}
