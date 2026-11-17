package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
)

// Private stdin control; never exposes WG keys or a public administration port.
func applyTargetUpdates(input io.Reader, policy *sitePolicy, output io.Writer, russian ...*russianRouter) error {
	var router *russianRouter
	if len(russian) > 0 {
		router = russian[0]
	}
	return applyRouterUpdates(input, policy, output, router, nil)
}

func applyRouterUpdates(input io.Reader, policy *sitePolicy, output io.Writer, russian *russianRouter, networkChanged func(), setWireguard ...func(string) error) error {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 4096), 2*1024*1024)
	var networkEpoch uint64
	for scanner.Scan() {
		var update struct {
			Russian      *russianConfig `json:"russian"`
			Revision     int64          `json:"revision"`
			Targets      *[]string      `json:"targets"`
			NetworkEpoch uint64         `json:"network_epoch"`
			PhysicalDNS  *[]string      `json:"physical_dns"`
			Wireguard    *string        `json:"wireguard"`
		}
		if json.Unmarshal(scanner.Bytes(), &update) != nil || update.Revision <= 0 || (update.Targets != nil && len(*update.Targets) > 16384) {
			continue
		}
		if update.Wireguard != nil {
			if len(setWireguard) == 0 || len(*update.Wireguard) > 65536 || setWireguard[0](*update.Wireguard) != nil {
				fmt.Fprintf(output, "WG_FAILED:%d\n", update.Revision)
				continue
			}
		}
		if update.Targets != nil {
			policy.replaceTargets(*update.Targets)
		}
		if update.Russian != nil && russian != nil {
			russian.update(*update.Russian)
		}
		if update.NetworkEpoch > networkEpoch && networkChanged != nil {
			if update.PhysicalDNS != nil && russian != nil {
				russian.updateDNS(*update.PhysicalDNS)
			}
			networkChanged()
			networkEpoch = update.NetworkEpoch
		}
		fmt.Fprintf(output, "POLICY_READY:%d\n", update.Revision)
	}
	return scanner.Err()
}
