package main

import (
	"context"
	"log"
	"time"
)

// acquireGroupCredentials owns credential acquisition before a group starts its workers.
func acquireGroupCredentials(ctx context.Context, groupID int, fetch func(context.Context) (*Credentials, error), handoff func()) (*Credentials, error) {
	wait := 5 * time.Second
	handedOff := false
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		creds, err := fetch(ctx)
		if err == nil {
			return creds, nil
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if !vkCallsShouldRetry(err) {
			return nil, err
		}
		// Let other groups progress while this group waits for VK to recover.
		if !handedOff {
			handedOff = true
			if handoff != nil {
				handoff()
			}
		}
		log.Printf("[ГРУППА #%d] Временная ошибка кредов: %v; повтор через %s", groupID, err, wait)
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
		wait = min(wait*2, 30*time.Second)
	}
}
