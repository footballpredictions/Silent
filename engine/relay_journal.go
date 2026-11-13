package main

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// The shared engine also logs credentials and addresses. Render only known
// events and validated numeric fields, never forward the original log line.
var relayLine = regexp.MustCompile(`\[(ВОРКЕР|СЕССИЯ|ГРУППА) #([0-9]{1,3})\] ([^\r\n]*)$`)
var relayCount = regexp.MustCompile(`\[ДИСП\] Воркер #([0-9]{1,3}) (зарегистрирован \(всего|отключён \(осталось): ([0-9]{1,3})\)$`)
var relayTraffic = regexp.MustCompile(`\[СТАТИСТИКА\] Активных: ([0-9]{1,3}) \| Трафик: ([0-9]{1,10}\.[0-9]{2}) МБ$`)

func relayJournalEvent(line string) (message string, level int) {
	line = strings.TrimSpace(line)
	if m := relayCount.FindStringSubmatch(line); m != nil {
		verb := "активен"
		if strings.HasPrefix(m[2], "отключён") {
			verb = "отключён"
		}
		return fmt.Sprintf("Воркер №%s %s · активных каналов: %s", m[1], verb, m[3]), 0
	}
	if m := relayTraffic.FindStringSubmatch(line); m != nil {
		return fmt.Sprintf("Активных каналов: %s · трафик: %s МБ", m[1], m[2]), 0
	}
	if strings.Contains(line, "[FATAL] panic ") {
		return "Внутренняя ошибка сетевого модуля", 2
	}
	m := relayLine.FindStringSubmatch(line)
	if m == nil {
		return "", 0
	}
	id, _ := strconv.Atoi(m[2])
	if id == 0 || id > 27 {
		return "", 0
	}
	prefix := fmt.Sprintf("Воркер №%d · ", id)
	if m[1] == "ГРУППА" {
		prefix = fmt.Sprintf("Группа №%d · ", id)
	}
	switch event := m[3]; {
	case strings.HasPrefix(event, "Креды OK, TURN:"):
		return prefix + "VK выдал параметры TURN", 1
	case strings.HasPrefix(event, "TURN UDP ("):
		return prefix + "подключение к TURN по UDP", 0
	case strings.HasPrefix(event, "Relay: "):
		return prefix + "TURN выделил канал", 1
	case event == "[DTLS] Рукопожатие (Handshake)...":
		return prefix + "рукопожатие DTLS", 0
	case event == "[DTLS] Соединение установлено ✓":
		return prefix + "DTLS установлен", 1
	case event == "Конфиг получен" || event == "Конфиг уже был доставлен другим воркером":
		return prefix + "GETCONF: настройки получены", 1
	case strings.HasPrefix(event, "Ошибка конфига:") || strings.HasPrefix(event, "Сервер ещё не выдал WireGuard-конфиг"):
		return prefix + "GETCONF: настройки не получены", 2
	case strings.HasPrefix(event, "[TURN] Квота relay"):
		return prefix + "TURN: квота каналов, ожидаем повтор", 2
	case strings.HasPrefix(event, "[TURN] Allocate") || strings.HasPrefix(event, "[TURN] Ошибка allocation"):
		return prefix + "TURN: сбой выделения канала, повтор", 2
	case strings.HasPrefix(event, "DTLS handshake — повтор"):
		return prefix + "DTLS: таймаут, повтор", 2
	case strings.HasPrefix(event, "Фатальная ошибка:"):
		return prefix + "ретранслятор отклонил подключение", 2
	case strings.HasPrefix(event, "Ошибка (попытка"):
		return prefix + "ошибка канала, повтор подключения", 2
	case strings.HasPrefix(event, "Ошибка Reader:") || strings.HasPrefix(event, "Ошибка Writer:"):
		return prefix + "соединение с ретранслятором прервалось", 2
	case event == "Все воркеры группы завершились.":
		return prefix + "воркеры остановлены", 0
	}
	return "", 0
}
