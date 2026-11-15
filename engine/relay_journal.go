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
var relayTURNCode = regexp.MustCompile(` · код ([3-6][0-9]{2})$`)

func relayTURNFailure(event, message string) string {
	if code := relayTURNCode.FindStringSubmatch(event); code != nil {
		return message + " · код " + code[1]
	}
	if strings.HasSuffix(event, " · таймаут") {
		return message + " · таймаут"
	}
	return message
}

func relaySocketFailure(event string) string {
	direction, operation := "чтения", "чтении"
	if strings.Contains(event, " Writer:") {
		direction, operation = "записи", "записи"
	}
	layer := "DTLS"
	if strings.HasPrefix(event, "Ошибка TURN ") {
		layer = "TURN"
	}
	lower := strings.ToLower(event)
	switch {
	case strings.HasSuffix(lower, "eof"):
		return layer + ": ретранслятор закрыл соединение (EOF)"
	case strings.Contains(lower, "network is unreachable"), strings.Contains(lower, "network is down"), strings.Contains(lower, "no route to host"):
		return layer + ": сеть недоступна при " + operation
	case strings.Contains(lower, "timeout"), strings.Contains(lower, "timed out"):
		return layer + ": таймаут " + direction
	case strings.Contains(lower, "closed pipe"), strings.Contains(lower, "closed network connection"):
		return layer + ": локальный канал закрыт при " + operation
	case strings.Contains(lower, "connection reset"), strings.Contains(lower, "connection refused"):
		return layer + ": соединение отклонено при " + operation
	default:
		return layer + ": ошибка " + direction + " канала"
	}
}

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
		return fmt.Sprintf("[СТАТИСТИКА] Активных: %s | Трафик: %s МБ", m[1], m[2]), 0
	}
	if strings.Contains(line, "[FATAL] panic ") {
		return "Внутренняя ошибка сетевого модуля", 2
	}
	m := relayLine.FindStringSubmatch(line)
	if m == nil {
		return "", 0
	}
	id, _ := strconv.Atoi(m[2])
	if id == 0 || id > 63 {
		return "", 0
	}
	prefix := fmt.Sprintf("Воркер №%d · ", id)
	if m[1] == "ГРУППА" {
		prefix = fmt.Sprintf("Группа №%d · ", id)
	}
	switch event := m[3]; {
	case strings.HasPrefix(event, "Креды OK, TURN:"):
		return "[VK] Параметры TURN получены", 1
	case strings.HasPrefix(event, "TURN UDP ("):
		return "[TURN] Подключение по UDP", 0
	case strings.HasPrefix(event, "Relay: "):
		return "[TURN] Канал выделен", 1
	case event == "[DTLS] Рукопожатие (Handshake)...":
		return "[DTLS] Рукопожатие…", 0
	case event == "[DTLS] Соединение установлено ✓":
		return "[DTLS] Соединение установлено ✓", 1
	case event == "Конфиг получен" || event == "Конфиг уже был доставлен другим воркером":
		return fmt.Sprintf("[ВОРКЕР #%d] Конфиг получен", id), 1
	case event == "[READY] Туннель готов к работе ✓":
		return "[READY] Канал готов ✓", 1
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
	case strings.HasPrefix(event, "Ошибка Reader:") || strings.HasPrefix(event, "Ошибка Writer:") || strings.HasPrefix(event, "Ошибка TURN Reader:") || strings.HasPrefix(event, "Ошибка TURN Writer:"):
		return prefix + relaySocketFailure(event), 2
	case event == "Keepalive: запись не прошла, канал закрывается":
		return prefix + "DTLS: ошибка keepalive, канал закрывается", 2
	case event == "Access-check: запись не прошла, канал закрывается":
		return prefix + "DTLS: ошибка проверки доступа, канал закрывается", 2
	case event == "TURN: NAT изменился, старый канал недействителен":
		return prefix + "сеть: NAT изменился, канал обновляется", 0
	case event == "TURN: физическая сеть изменилась, нужен новый сокет":
		return prefix + "сеть: обновляем UDP-сокет после смены интерфейса", 0
	case event == "TURN: канал не отвечает на повторную проверку после потери сети":
		return prefix + "TURN: нет ответа на две проверки · обновляем недоступный канал", 2
	case strings.HasPrefix(event, "TURN: продление allocation не подтверждено, канал закрывается"):
		return prefix + relayTURNFailure(event, "TURN: ошибка продления канала"), 2
	case strings.HasPrefix(event, "TURN: продление permission не подтверждено, канал закрывается"):
		return prefix + relayTURNFailure(event, "TURN: ошибка продления разрешения"), 2
	case event == "Все воркеры группы завершились.":
		return prefix + "воркеры остановлены", 0
	}
	return "", 0
}
