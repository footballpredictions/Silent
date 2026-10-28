package routerpolicy

// PreservesLearned permits retaining IP sets only when every previously direct
// name stays direct and the forced-VPN rules are unchanged. Restrictive changes
// still require invalidation; IPs alone cannot identify which name produced them.
func PreservesLearned(old, next Policy) bool {
	if old.Schema != 1 || next.Schema != 1 || old.Direct == nil || next.Direct == nil || old.VPN == nil || next.VPN == nil {
		return false
	}
	before, after := map[string]bool{}, map[string]bool{}
	for _, d := range old.VPN {
		before[d] = true
	}
	for _, d := range next.VPN {
		after[d] = true
	}
	if len(before) != len(after) {
		return false
	}
	for d := range before {
		if !after[d] {
			return false
		}
	}
	for _, d := range old.Direct {
		if !Suffix(d, next.Direct) {
			return false
		}
	}
	for _, d := range old.Exact {
		if old.Match(d) == Direct && next.Match(d) != Direct {
			return false
		}
	}
	return true
}
