package main

import (
	"net"
	"time"
)

// newVkDirectDialer — на Android только обычный dialer.
// Кастомный PreferGo+публичный DNS даёт lookup i/o timeout на LTE
// (оператор режет 8.8.8.8 / ломает DoH-путь); system DNS работает.
// Обход Wi‑Fi poison — ротация api.vk.me → api.vk.ru → api.vk.com.
func newVkDirectDialer() net.Dialer {
	return net.Dialer{
		Timeout:   20 * time.Second,
		KeepAlive: 30 * time.Second,
	}
}
