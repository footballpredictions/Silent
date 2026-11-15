package main

import (
	"context"
	"log"
	"regexp"
	"strings"

	"github.com/pion/logging"
)

// A TURN allocation can expire without a UDP write failing. Pion's renewal
// errors are only reported to its logger. End that session so the existing
// WorkerGroup retry loop can allocate a usable channel; keep WireGuard up.
type iosTURNLoggerFactory struct {
	ctx       context.Context
	cancel    context.CancelFunc
	sessionID int
}

func (f *iosTURNLoggerFactory) NewLogger(_ string) logging.LeveledLogger {
	return &iosTURNLogger{owner: f}
}

type iosTURNLogger struct {
	NullLogger
	owner *iosTURNLoggerFactory
}

var iosTURNRejectedCode = regexp.MustCompile(`^TURN refresh rejected \(([3-6][0-9]{2})\)$`)

func (l *iosTURNLogger) Warnf(format string, args ...interface{}) {
	if l.owner.ctx.Err() != nil {
		return
	}
	var event string
	switch format {
	case "Failed to refresh allocation: %s":
		event = "TURN: продление allocation не подтверждено, канал закрывается"
	case "Failed to refresh permissions: %s":
		event = "TURN: продление permission не подтверждено, канал закрывается"
	default:
		return
	}
	if len(args) == 1 {
		if err, ok := args[0].(error); ok {
			if code := iosTURNRejectedCode.FindStringSubmatch(err.Error()); code != nil {
				event += " · код " + code[1]
			} else if text := strings.ToLower(err.Error()); strings.Contains(text, "timeout") || strings.Contains(text, "timed out") {
				event += " · таймаут"
			}
		}
	}
	// Do not expose server addresses, credentials or the original library args.
	log.Printf("[ВОРКЕР #%d] %s", l.owner.sessionID, event)
	l.owner.cancel()
}
