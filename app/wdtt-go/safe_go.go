package main

import (
	"log"
	"runtime/debug"
)

func safeGo(name string, fn func()) {
	go func() {
		defer func() {
			if r := recover(); r != nil {
				writeCrashLog("safeGo:"+name, r)
				log.Printf("[FATAL] panic in %s: %v", name, r)
				debug.PrintStack()
			}
		}()
		fn()
	}()
}
