package main

import (
	"net"
	"slices"
	"unsafe"

	"golang.org/x/sys/windows"
)

func vkAdapterDNS(localIP net.IP) []string {
	if localIP == nil {
		return nil
	}
	size := uint32(15 * 1024)
	for attempt := 0; attempt < 2 && size <= 256*1024; attempt++ {
		buffer := make([]byte, size)
		first := (*windows.IpAdapterAddresses)(unsafe.Pointer(&buffer[0]))
		err := windows.GetAdaptersAddresses(windows.AF_INET, 0, 0, first, &size)
		if err == windows.ERROR_BUFFER_OVERFLOW {
			continue
		}
		if err != nil {
			return nil
		}
		for adapter := first; adapter != nil; adapter = adapter.Next {
			if adapter.OperStatus != windows.IfOperStatusUp {
				continue
			}
			for addr := adapter.FirstUnicastAddress; addr != nil; addr = addr.Next {
				if localIP.Equal(addr.Address.IP()) {
					return ipv4AdapterDNSServers(adapter.FirstDnsServerAddress)
				}
			}
		}
		return nil
	}
	return nil
}

func ipv4AdapterDNSServers(first *windows.IpAdapterDnsServerAdapter) []string {
	var servers []string
	for entry := first; entry != nil && len(servers) < 2; entry = entry.Next {
		ip := entry.Address.IP().To4()
		if ip == nil || ip.IsLoopback() || ip.IsUnspecified() || ip.Equal(net.IPv4(10, 66, 66, 1)) {
			continue
		}
		address := net.JoinHostPort(ip.String(), "53")
		if !slices.Contains(servers, address) {
			servers = append(servers, address)
		}
	}
	return servers
}
