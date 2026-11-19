'use strict'

// Consume existing transport events; never retain credentials, addresses or raw errors.
function createWorkerProgress() {
  const workers = new Map()
  function observe(line) {
    const text = String(line || '')
    let match = text.match(/\[ДИСП\] Воркер #(\d+) (зарегистрирован|отключён)/)
    if (match) {
      const id = Number(match[1])
      workers.set(id, match[2] === 'зарегистрирован' ? { stage: 'ready' } : { stage: 'retry', reason: 'соединение закрыто' })
      return
    }
    match = text.match(/\[(ВОРКЕР|СЕССИЯ) #(\d+)\]/)
    if (!match) return
    const id = Number(match[2])
    if (!Number.isInteger(id) || id < 1 || id > 108) return
    if (/Невосстановимая|Фатальная ошибка/.test(text)) {
      workers.set(id, { stage: 'stopped', reason: reasonFor(text) })
    } else if (/Ошибка|повтор|ждём|timeout|неполный ответ/i.test(text)) {
      workers.set(id, { stage: 'retry', reason: reasonFor(text) })
    } else if (/TURN UDP/.test(text)) {
      workers.set(id, { stage: 'turn' })
    } else if (/Relay:|Рукопожатие/.test(text)) {
      workers.set(id, { stage: 'dtls' })
    } else if (/Соединение установлено|Запрос конфига/.test(text)) {
      workers.set(id, { stage: 'config' })
    }
  }
  function reasonFor(text) {
    if (/quota|486|квот/i.test(text)) return 'TURN квота'
    const turnStatus = text.match(/\b(403|437|438|401)\b/)
    if (turnStatus) return `TURN ${turnStatus[1]}`
    if (/cannot create socket|error 29/i.test(text)) return 'сокет/STUN'
    if (/WRAP_AUTH_TIMEOUT|DTLS.*(timeout|handshake|повтор)|хендшейк/i.test(text)) return 'DTLS таймаут'
    if (/TURN.*(retransmission|timeout|allocate)/i.test(text)) return 'TURN Allocate'
    if (/неполный ответ|attribute not found/i.test(text)) return 'TURN неполный ответ'
    if (/конфиг/i.test(text)) return 'GETCONF'
    if (/Reader|Writer|read|write/i.test(text)) return 'передача данных'
    return 'сеть'
  }
  function snapshot(target, active) {
    const counts = { ready: 0, turn: 0, dtls: 0, config: 0, retry: 0, stopped: 0 }
    const reasons = new Map()
    let observed = 0
    for (const [id, worker] of workers) {
      if (id > target) continue
      observed++
      if (worker.stage in counts) counts[worker.stage]++
      if (worker.reason) reasons.set(worker.reason, (reasons.get(worker.reason) || 0) + 1)
    }
    return {
      active, target, ...counts, queued: Math.max(0, target - observed),
      reasons: [...reasons].sort((a, b) => b[1] - a[1]).map(([reason, count]) => `${reason}=${count}`).join(', '),
    }
  }
  function format(target, active) {
    const s = snapshot(target, active)
    return `[Workers] Готово=${s.ready}/${s.target}; соединений=${s.active}; TURN=${s.turn}; DTLS=${s.dtls}; GETCONF=${s.config}; повторы=${s.retry}; остановлены=${s.stopped}; ещё не стартовали=${s.queued}${s.reasons ? '; причины: ' + s.reasons : ''}`
  }
  return { observe, snapshot, format, reset: () => workers.clear() }
}

module.exports = { createWorkerProgress }
