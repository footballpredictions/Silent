//go:build android

package main

import "runtime/debug"

func init() {
	// Паники в stderr для Kotlin log reader ([FATAL] panic).
	debug.SetTraceback("all")
}
