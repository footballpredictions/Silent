package main

import (
	"net/netip"
	"sync"
	"time"
)

type sitePolicy struct {
	whitelist bool
	targets   []netip.Prefix
	browsers  map[int]bool
	domains   []string
	mu        sync.RWMutex
	learned   map[netip.Addr]time.Time
	now       func() time.Time
}

func newPolicy(whitelist bool, targets []string, browsers []int) *sitePolicy {
	p := &sitePolicy{whitelist: whitelist, browsers: make(map[int]bool), learned: make(map[netip.Addr]time.Time), now: time.Now}
	for _, uid := range browsers {
		if uid >= 0 {
			p.browsers[uid] = true
		}
	}
	for _, raw := range targets {
		prefix, err := netip.ParsePrefix(raw)
		if err != nil {
			if addr, e := netip.ParseAddr(raw); e == nil {
				prefix = netip.PrefixFrom(addr, addr.BitLen())
				err = nil
			}
		}
		if err == nil {
			p.targets = append(p.targets, prefix.Masked())
		}
	}
	return p
}

func (p *sitePolicy) direct(uid int, destination netip.Addr) bool {
	if !p.browsers[uid] || netip.MustParsePrefix("10.66.66.0/24").Contains(destination) {
		return false
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	found := false
	for _, target := range p.targets {
		if target.Contains(destination) {
			found = true
			break
		}
	}
	if !found {
		until, exists := p.learned[destination]
		found = exists && p.now().Before(until)
	}
	if p.whitelist {
		return !found
	}
	return found
}

// DNS warm-up targets may rotate while the device, rules and app policy stay put.
// Learned DNS and cached flow decisions belong to the running tunnel.
func (p *sitePolicy) replaceTargets(targets []string) {
	next := newPolicy(false, targets, nil)
	p.mu.Lock()
	p.targets = next.targets
	p.mu.Unlock()
}
