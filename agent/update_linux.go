package main

import (
	"os"
	"os/exec"
	"syscall"

	"golang.org/x/sys/unix"
)

func processAlive(pid int) bool { return pid > 1 && unix.Kill(pid, 0) == nil }
func launchUpdate(path, root string) (int, error) {
	executable, err := os.Executable()
	if err != nil {
		return 0, err
	}
	cmd := exec.Command(executable, "--update-worker", "--config", path, "--root", root)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err = cmd.Start(); err != nil {
		return 0, err
	}
	go func() { _ = cmd.Wait() }()
	return cmd.Process.Pid, nil
}
func diskFree(path string) (uint64, error) {
	var s unix.Statfs_t
	if err := unix.Statfs(path, &s); err != nil {
		return 0, err
	}
	return uint64(s.Bavail) * uint64(s.Bsize), nil
}
func memoryAvailable() (uint64, error) {
	b, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0, err
	}
	return parseMemoryAvailable(b)
}
