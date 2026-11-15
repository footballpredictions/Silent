// SPDX-License-Identifier: MIT
package client

import (
	"errors"
	"time"
)

// Refresh revalidates the TURN data path after the process was suspended.
// A STUN Binding response validates only the local mapped address: it says
// nothing about the lifetime of the allocation, permission or channel.
// Keep the same allocation and channel number whenever the server accepts them.
func (c *UDPConn) Refresh() error {
	select {
	case <-c.closeCh:
		return errClosed
	default:
	}
	retry := func(operation func() error) error {
		var err error
		for i := 0; i < maxRetryAttempts; i++ {
			err = operation()
			if !errors.Is(err, errTryAgain) {
				return err
			}
		}
		return err
	}
	if err := retry(func() error { return c.refreshAllocation(c.lifetime(), false) }); err != nil {
		return err
	}
	if err := retry(c.refreshPermissions); err != nil {
		return err
	}
	for _, bound := range c.bindingMgr.all() {
		// bind does not alter state on failure. A transient refresh failure
		// must not make an otherwise valid existing binding unusable.
		if err := retry(func() error { return c.bind(bound) }); err != nil {
			return err
		}
		bound.setRefreshedAt(time.Now())
		bound.setState(bindingStateReady)
	}
	return nil
}
