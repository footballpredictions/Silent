package main

import "testing"

func TestRelayJournalOnlyPublishesStructuredEvents(t *testing.T) {
	for _, tc := range []struct {
		raw, message string
		level        int
	}{
		{"[ГРУППА #1] Запрос кредов (хеш: confidential...)", "", 0},
		{"[STREAM 100] VK token=confidential", "", 0},
		{"[ГРУППА #1] Креды OK, TURN: [turn:192.0.2.1], 3 воркеров", "Группа №1 · VK выдал параметры TURN", 1},
		{"[СЕССИЯ #2] Relay: 192.0.2.1:5432", "Воркер №2 · TURN выделил канал", 1},
		{"[ВОРКЕР #2] [DTLS] Соединение установлено ✓", "Воркер №2 · DTLS установлен", 1},
		{"[ВОРКЕР #2] Ошибка конфига: private-key=confidential", "Воркер №2 · GETCONF: настройки не получены", 2},
		{"[ВОРКЕР #2] [TURN] Квота relay, ждём без refresh кредов (попытка 1): confidential", "Воркер №2 · TURN: квота каналов, ожидаем повтор", 2},
		{"[ДИСП] Воркер #2 зарегистрирован (всего: 3)", "Воркер №2 активен · активных каналов: 3", 0},
		{"[ДИСП] Воркер #2 отключён (осталось: 1)", "Воркер №2 отключён · активных каналов: 1", 0},
		{"[ВОРКЕР #63] [DTLS] Соединение установлено ✓", "Воркер №63 · DTLS установлен", 1},
		{"[ВОРКЕР #64] [DTLS] Соединение установлено ✓", "", 0},
	} {
		message, level := relayJournalEvent("2026/11/13 16:45:21 " + tc.raw + "\n")
		if message != tc.message || level != tc.level {
			t.Errorf("got (%q, %d), want (%q, %d)", message, level, tc.message, tc.level)
		}
	}
}
