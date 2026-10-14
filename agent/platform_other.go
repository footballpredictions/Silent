//go:build !linux

package main

import (
	"context"
	"fmt"
	"net"
)

// Host builds exist only for portable tests; router distributions are Linux only.
func (a *Agent) connect(context.Context) error    { return fmt.Errorf("Keenetic agent requires Linux") }
func (a *Agent) disconnect() error                { return nil }
func (a *Agent) interrupt()                       {}
func (a *Agent) watch(context.Context)            {}
func (a *Agent) tunnelReady() bool                { return false }
func boundDialer(ip string, tcp bool) *net.Dialer { return &net.Dialer{} }
func processLock(path string) (func(), error)     { return func() {}, nil }
func processAlive(pid int) bool                   { return false }
func launchUpdate(path, root string) (int, error) { return 0, fmt.Errorf("Updater requires Linux") }
func diskFree(path string) (uint64, error)        { return 0, fmt.Errorf("Updater requires Linux") }
func memoryAvailable() (uint64, error)            { return 0, fmt.Errorf("Updater requires Linux") }
