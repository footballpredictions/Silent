package main

import (
	"encoding/binary"
	"golang.org/x/sys/windows"
	"net/netip"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

var ipHelper = windows.NewLazySystemDLL("iphlpapi.dll")
var tcpTable = ipHelper.NewProc("GetExtendedTcpTable")
var udpTable = ipHelper.NewProc("GetExtendedUdpTable")
var setTCPEntry = ipHelper.NewProc("SetTcpEntry")

func tcpDeleteRow(f flow) ([20]byte, error) {
	var row [20]byte
	local, e := netip.ParseAddrPort(f.Local)
	if e != nil || !local.Addr().Is4() {
		return row, windows.ERROR_INVALID_PARAMETER
	}
	remote, e := netip.ParseAddrPort(f.Remote)
	if e != nil || !remote.Addr().Is4() {
		return row, windows.ERROR_INVALID_PARAMETER
	}
	binary.LittleEndian.PutUint32(row[:4], 12) // MIB_TCP_STATE_DELETE_TCB
	a, b := local.Addr().As4(), remote.Addr().As4()
	copy(row[4:8], a[:])
	copy(row[12:16], b[:])
	binary.BigEndian.PutUint16(row[8:10], local.Port())
	binary.BigEndian.PutUint16(row[16:18], remote.Port())
	return row, nil
}

func resetTCPConnection(f flow) error {
	row, e := tcpDeleteRow(f)
	if e != nil {
		return e
	}
	result, _, _ := setTCPEntry.Call(uintptr(unsafe.Pointer(&row[0])))
	if result == 0 || result == uintptr(windows.ERROR_NOT_FOUND) || result == uintptr(windows.ERROR_INVALID_PARAMETER) {
		return nil
	}
	return windows.Errno(result)
}

func ownerTable(proc *windows.LazyProc, class uintptr) []byte {
	var size uint32
	proc.Call(0, uintptr(unsafe.Pointer(&size)), 0, windows.AF_INET, class, 0)
	if size < 4 || size > 16*1024*1024 {
		return nil
	}
	for i := 0; i < 3; i++ {
		b := make([]byte, size)
		result, _, _ := proc.Call(uintptr(unsafe.Pointer(&b[0])), uintptr(unsafe.Pointer(&size)), 0, windows.AF_INET, class, 0)
		if result == 0 {
			return b
		}
		if result != uintptr(windows.ERROR_INSUFFICIENT_BUFFER) || size > 16*1024*1024 {
			return nil
		}
	}
	return nil
}

// An ambiguous UDP binding is unknown, rather than another process's exemption.
func ownerPID(f flow) uint32 {
	local, e := netip.ParseAddrPort(f.Local)
	if e != nil {
		return 0
	}
	remote, e := netip.ParseAddrPort(f.Remote)
	if e != nil {
		return 0
	}
	var b []byte
	stride, ipOffset, portOffset, pidOffset := 24, 4, 8, 20
	if f.Protocol == 6 {
		b = ownerTable(tcpTable, 5)
	} else if f.Protocol == 17 {
		b = ownerTable(udpTable, 1)
		stride, ipOffset, portOffset, pidOffset = 12, 0, 4, 8
	} else {
		return 0
	}
	if len(b) < 4 {
		return 0
	}
	count := int(binary.LittleEndian.Uint32(b[:4]))
	if count > (len(b)-4)/stride {
		return 0
	}
	var found uint32
	for i := 0; i < count; i++ {
		row := b[4+i*stride : 4+(i+1)*stride]
		if binary.BigEndian.Uint16(row[portOffset:portOffset+2]) != local.Port() {
			continue
		}
		addr := netip.AddrFrom4([4]byte(row[ipOffset : ipOffset+4]))
		if addr != local.Addr() && !(f.Protocol == 17 && addr.IsUnspecified()) {
			continue
		}
		if f.Protocol == 6 && (netip.AddrFrom4([4]byte(row[12:16])) != remote.Addr() || binary.BigEndian.Uint16(row[16:18]) != remote.Port()) {
			continue
		}
		pid := binary.LittleEndian.Uint32(row[pidOffset : pidOffset+4])
		if found != 0 && found != pid {
			return 0
		}
		found = pid
	}
	return found
}

func processExe(pid uint32) string {
	if pid == 0 {
		return ""
	}
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, pid)
	if err != nil {
		return ""
	}
	defer windows.CloseHandle(handle)
	buf := make([]uint16, 32768)
	size := uint32(len(buf))
	if windows.QueryFullProcessImageName(handle, 0, &buf[0], &size) != nil {
		return ""
	}
	return windows.UTF16ToString(buf[:size])
}

var physicalIndex uint32

var ancestry struct {
	sync.Mutex
	until   time.Time
	parents map[uint32]uint32
}

func parentPIDs() map[uint32]uint32 {
	ancestry.Lock()
	defer ancestry.Unlock()
	if time.Now().Before(ancestry.until) {
		return ancestry.parents
	}
	parents := make(map[uint32]uint32)
	snapshot, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return parents
	}
	defer windows.CloseHandle(snapshot)
	var entry windows.ProcessEntry32
	entry.Size = uint32(unsafe.Sizeof(entry))
	for err = windows.Process32First(snapshot, &entry); err == nil; err = windows.Process32Next(snapshot, &entry) {
		parents[entry.ProcessID] = entry.ParentProcessID
	}
	ancestry.parents = parents
	ancestry.until = time.Now().Add(time.Second)
	return parents
}

func ownerExe(f flow, policy *processPolicy) string {
	pid := ownerPID(f)
	exe := processExe(pid)
	if exe == "" || policy.appExcluded(exe) || len(policy.excluded) == 0 {
		return exe
	}
	parents := parentPIDs()
	for i := 0; i < 8; i++ {
		parent := parents[pid]
		if parent == 0 || parent == pid {
			break
		}
		pid = parent
		if ancestor := processExe(pid); policy.appExcluded(ancestor) {
			return ancestor
		}
	}
	return exe
}

func physicalDialer(timeout time.Duration) *netDialer { return newPhysicalDialer(timeout) }

func bindPhysical(network, address string, raw syscall.RawConn) error {
	if physicalIndex == 0 {
		return windows.ERROR_INVALID_PARAMETER
	}
	var sockErr error
	err := raw.Control(func(fd uintptr) {
		var bytes [4]byte
		binary.BigEndian.PutUint32(bytes[:], physicalIndex)
		index := binary.LittleEndian.Uint32(bytes[:])
		sockErr = windows.SetsockoptInt(windows.Handle(fd), windows.IPPROTO_IP, 31, int(index))
	})
	if err != nil {
		return err
	}
	return sockErr
}
