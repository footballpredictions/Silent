package main

import (
	"context"
	"net/netip"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// A bounded numeric snapshot is shared by a whole policy update, not one command per flow.
func macOwnerSnapshot(selector string, policy *processPolicy) func(flow) string {
	empty := func(flow) string { return "" }
	if len(policy.excluded) == 0 {
		return empty
	}
	ctx, cancel := context.WithTimeout(context.Background(), 350*time.Millisecond)
	defer cancel()
	data, err := exec.CommandContext(ctx, "/usr/sbin/lsof", "-nP", "-a", selector, "-F0pfPn").Output()
	if err != nil || len(data) > 1024*1024 {
		return empty
	}
	index := lsofSocketIndex(string(data))
	pids := make(map[string]bool)
	for _, entries := range index {
		for _, entry := range entries {
			pids[entry.identity] = true
		}
	}
	if len(pids) == 0 {
		return empty
	}
	ids := make([]string, 0, len(pids))
	for pid := range pids {
		ids = append(ids, pid)
	}
	names, err := exec.CommandContext(ctx, "/bin/ps", "-ww", "-p", strings.Join(ids, ","), "-o", "pid=,comm=").Output()
	if err != nil || len(names) > 1024*1024 {
		return empty
	}
	owners := make(map[string]string)
	for _, line := range strings.Split(string(names), "\n") {
		line = strings.TrimSpace(line)
		split := strings.IndexAny(line, " \t")
		if split < 0 {
			continue
		}
		pid, exe := line[:split], strings.TrimSpace(line[split:])
		if pids[pid] && policy.appExcluded(exe) {
			owners[pid] = exe
		}
	}
	return func(f flow) string { return owners[index.owner(f)] }
}
func applicationOwnerSnapshot(policy *processPolicy) func(flow) string {
	return macOwnerSnapshot("-i4", policy)
}
func ownerExe(f flow, policy *processPolicy) string {
	if f.Protocol != 6 && f.Protocol != 17 {
		return ""
	}
	local, err := netip.ParseAddrPort(f.Local)
	if err != nil {
		return ""
	}
	protocol := "TCP"
	if f.Protocol == 17 {
		protocol = "UDP"
	}
	return macOwnerSnapshot("-i4"+protocol+":"+strconv.Itoa(int(local.Port())), policy)(f)
}
