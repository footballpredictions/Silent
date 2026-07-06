package main

import (
	"fmt"
	"os"
	"time"
)

func writeCrashLog(prefix string, detail interface{}) {
	line := fmt.Sprintf("%s %v: %v\n", time.Now().Format("2006-01-02 15:04:05"), prefix, detail)
	_, _ = os.Stderr.WriteString(line)
	f, err := os.OpenFile("libclient-crash.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
	if err != nil {
		return
	}
	_, _ = f.WriteString(line)
	_ = f.Close()
}

func safeCloseChan(ch chan struct{}) {
	if ch == nil {
		return
	}
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("safeCloseChan", r)
		}
	}()
	close(ch)
}

func safeCloseStringChan(ch chan string) {
	if ch == nil {
		return
	}
	defer func() {
		if r := recover(); r != nil {
			writeCrashLog("safeCloseStringChan", r)
		}
	}()
	close(ch)
}
