package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
)

// Private stdin control; never exposes WG keys or a public administration port.
func applyTargetUpdates(input io.Reader, policy *sitePolicy, output io.Writer, russian ...*russianRouter) error {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 4096), 2*1024*1024)
	for scanner.Scan() {
		var update struct {
			Russian  *russianConfig `json:"russian"`
			Revision int64          `json:"revision"`
			Targets  []string       `json:"targets"`
		}
		if json.Unmarshal(scanner.Bytes(), &update) != nil || update.Revision <= 0 || len(update.Targets) > 16384 {
			continue
		}
		policy.replaceTargets(update.Targets)
		if update.Russian != nil && len(russian) > 0 {
			russian[0].update(*update.Russian)
		}
		fmt.Fprintf(output, "POLICY_READY:%d\n", update.Revision)
	}
	return scanner.Err()
}
