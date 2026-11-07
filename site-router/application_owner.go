package main

import (
	"encoding/hex"
	"net/netip"
	"path"
	"strconv"
	"strings"
)

func matchesApplication(exe, selected, platform string) bool {
	if exe == "" || selected == "" {
		return false
	}
	if platform != "windows" && strings.HasPrefix(exe, "/") {
		exe, selected = path.Clean(exe), path.Clean(selected)
		if platform == "darwin" && strings.HasSuffix(selected, ".app") {
			return exe == selected || strings.HasPrefix(exe, selected+"/")
		}
		return exe == selected || (!strings.Contains(selected, "/") && path.Base(exe) == selected)
	}
	return normalizedExe(exe) == normalizedExe(selected) || exeLeaf(exe) == exeLeaf(selected)
}

func procEndpoint(raw string) (netip.AddrPort, bool) {
	ipHex, portHex, ok := strings.Cut(raw, ":")
	if !ok {
		return netip.AddrPort{}, false
	}
	ip, err := hex.DecodeString(ipHex)
	port, portErr := strconv.ParseUint(portHex, 16, 16)
	if err != nil || portErr != nil || (len(ip) != 4 && len(ip) != 16) {
		return netip.AddrPort{}, false
	}
	for i := 0; i < len(ip); i += 4 {
		ip[i], ip[i+1], ip[i+2], ip[i+3] = ip[i+3], ip[i+2], ip[i+1], ip[i]
	}
	addr, ok := netip.AddrFromSlice(ip)
	return netip.AddrPortFrom(addr.Unmap(), uint16(port)), ok
}

// A snapshot is indexed by protocol/local port, never by a shared remote IP.
type ownerSocket struct {
	local, remote netip.AddrPort
	connected     bool
	identity      string
}
type socketOwnerIndex map[uint32][]ownerSocket

func ownerPort(protocol uint8, port uint16) uint32 { return uint32(protocol)<<16 | uint32(port) }
func (index socketOwnerIndex) owner(f flow) string {
	local, err := netip.ParseAddrPort(f.Local)
	if err != nil {
		return ""
	}
	remote, err := netip.ParseAddrPort(f.Remote)
	if err != nil {
		return ""
	}
	best, owner, ambiguous := -1, "", false
	for _, entry := range index[ownerPort(uint8(f.Protocol), local.Port())] {
		score := 0
		if entry.local.Addr() == local.Addr() {
			score += 2
		} else if f.Protocol != 17 || !entry.local.Addr().IsUnspecified() {
			continue
		}
		if entry.connected {
			if entry.remote != remote {
				continue
			}
			score += 4
		} else if f.Protocol != 17 {
			continue
		}
		if score > best {
			best, owner, ambiguous = score, entry.identity, false
		} else if score == best && owner != entry.identity {
			ambiguous = true
		}
	}
	if ambiguous {
		return ""
	}
	return owner
}
func addProcSockets(index socketOwnerIndex, table string, protocol uint8) {
	for _, line := range strings.Split(table, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 10 || fields[9] == "0" {
			continue
		}
		local, ok := procEndpoint(fields[1])
		if !ok {
			continue
		}
		remote, ok := procEndpoint(fields[2])
		if !ok {
			continue
		}
		connected := !remote.Addr().IsUnspecified() || remote.Port() != 0
		key := ownerPort(protocol, local.Port())
		index[key] = append(index[key], ownerSocket{local, remote, connected, fields[9]})
	}
}
func socketInode(tables []string, f flow) string {
	index := make(socketOwnerIndex)
	for _, table := range tables {
		addProcSockets(index, table, uint8(f.Protocol))
	}
	return index.owner(f)
}
func lsofSocketIndex(snapshot string) socketOwnerIndex {
	index := make(socketOwnerIndex)
	pid, protocol, name := "", "", ""
	flush := func() {
		number, err := strconv.Atoi(pid)
		if err != nil || number <= 0 || name == "" {
			return
		}
		var proto uint8
		if protocol == "TCP" {
			proto = 6
		} else if protocol == "UDP" {
			proto = 17
		} else {
			return
		}
		parts := strings.SplitN(name, "->", 2)
		local, err := netip.ParseAddrPort(strings.Replace(parts[0], "*:", "0.0.0.0:", 1))
		if err != nil {
			return
		}
		var remote netip.AddrPort
		if len(parts) == 2 {
			remote, err = netip.ParseAddrPort(parts[1])
			if err != nil {
				return
			}
		}
		key := ownerPort(proto, local.Port())
		index[key] = append(index[key], ownerSocket{local, remote, len(parts) == 2, pid})
	}
	for _, field := range strings.Split(snapshot, "\x00") {
		field = strings.TrimLeft(field, "\n\r")
		if len(field) < 2 {
			continue
		}
		switch field[0] {
		case 'p':
			flush()
			pid = field[1:]
			protocol, name = "", ""
		case 'f':
			flush()
			protocol, name = "", ""
		case 'P':
			protocol = field[1:]
		case 'n':
			name = field[1:]
		}
	}
	flush()
	return index
}
func lsofOwner(snapshot string, f flow) int {
	pid, _ := strconv.Atoi(lsofSocketIndex(snapshot).owner(f))
	return pid
}
