/** Парсинг stdout libclient — как WdttTunnelManager на Android. */
function parseLibclientLine(lineTrim) {
  if (!lineTrim) return null

  if (lineTrim.startsWith('CAPTCHA_SOLVE|')) {
    const parts = lineTrim.split('|')
    const mode = parts[1] || 'auto'
    const n = (parts[2] || '').length + (parts[3] || '').length
    return {
      key: 'captcha_solve_ui',
      message: `[КАПЧА] окно браузера (${mode}, ~${n} симв.)`,
      priority: 5,
      isError: false,
    }
  }

  if (lineTrim.includes('[СТАТИСТИКА]') || /Активных:\s*\d+/.test(lineTrim)) {
    const msg = lineTrim.includes('[СТАТИСТИКА]')
      ? (lineTrim.split('[СТАТИСТИКА]')[1] || '').trim()
      : lineTrim.trim()
    return { key: 'stats', message: `[СТАТИСТИКА] ${msg}`, priority: 3, isError: false }
  }

  const isError =
    /ошибка|error|fail|timeout|refused/i.test(lineTrim)

  if (
    lineTrim.includes('Конфиг получен') ||
    lineTrim.includes('Ошибка конфига') ||
    lineTrim.includes('Сервер ещё не выдал') ||
    lineTrim.includes('[КОНФИГ]')
  ) {
    const isNoconf = lineTrim.includes('Сервер ещё не выдал')
    const isErr = lineTrim.includes('Ошибка')
    const msg = isNoconf
      ? `${lineTrim} (GETCONF через TURN — HTTPS не нужен)`
      : lineTrim
    return {
      key: `getconf_${lineTrim.slice(0, 20).split('').reduce((a, c) => ((a << 5) - a + c.charCodeAt(0)) | 0, 0)}`,
      message: msg,
      priority: 2,
      isError: isErr || isNoconf,
    }
  }

  if (lineTrim.includes('[КАПЧА] AUTO:')) {
    const text = lineTrim.split('[КАПЧА] AUTO:')[1]?.trim() || ''
    return { key: `captcha_auto_${text.slice(0, 12)}`, message: `[КАПЧА AUTO] ${text}`, priority: 5, isError: isError }
  }
  if (lineTrim.includes('[КАПЧА] RJS:')) {
    const text = lineTrim.split('[КАПЧА] RJS:')[1]?.trim() || ''
    return { key: `captcha_rjs_${text.slice(0, 12)}`, message: `[КАПЧА RJS] ${text}`, priority: 5, isError: false }
  }
  if (lineTrim.includes('[КАПЧА] WBV:')) {
    const text = lineTrim.split('[КАПЧА] WBV:')[1]?.trim() || ''
    return { key: `captcha_wv_${text.slice(0, 12)}`, message: `[КАПЧА WBV] ${text}`, priority: 5, isError: isError }
  }
  if (lineTrim.includes('Старт') || lineTrim.includes('Ожидайте')) {
    return { key: 'creds_start', message: '[ВК] Получение учётных данных…', priority: 2, isError: false }
  }
  if (lineTrim.includes('Креды OK') || lineTrim.includes('Первые креды')) {
    return { key: 'creds_ok', message: '[ВК] Учётные данные проверены ✓', priority: 2, isError: false }
  }
  if (lineTrim.includes('Решаю VK Smart Captcha')) {
    return { key: 'captcha_start', message: '[КАПЧА] Решение капчи…', priority: 5, isError: false }
  }
  if (lineTrim.includes('Smart Captcha решена')) {
    return { key: 'captcha_done', message: '[КАПЧА] Капча решена ✓', priority: 5, isError: false }
  }
  if (lineTrim.includes('[WRAP]')) {
    return {
      key: 'wrap_status',
      message: `[WRAP] ${(lineTrim.split('[WRAP]')[1] || '').trim()}`,
      priority: 1,
      isError: false,
    }
  }
  if (lineTrim.includes('[TURN]')) {
    const text = (lineTrim.split('[TURN]')[1] || '').trim()
    return { key: `turn_${text.slice(0, 24)}`, message: `[TURN] ${text}`, priority: 2, isError: isError }
  }
  if (lineTrim.includes('Relay:') || lineTrim.includes('[DTLS] Рукопожатие')) {
    return { key: 'dtls_start', message: '[DTLS] Рукопожатие…', priority: 1, isError: false }
  }
  if (lineTrim.includes('DTLS ОК') || lineTrim.includes('Соединение установлено ✓')) {
    return { key: 'dtls_ok', message: '[DTLS] Соединение установлено ✓', priority: 1, isError: false }
  }
  if (lineTrim.includes('[READY]') || lineTrim.includes('Активна ✓')) {
    return { key: 'ready_line', message: '[READY] Туннель готов ✓', priority: 2, isError: false }
  }
  if (lineTrim.includes('зарегистрирован (всего:')) {
    return { key: 'workers_reg', message: lineTrim, priority: 2, isError: false }
  }

  // Ретраи воркеров — шум, не ошибка VPN (как Android: скрываем до isError)
  if (lineTrim.includes('[ВОРКЕР #') && !lineTrim.includes('[READY]') && !lineTrim.includes('зарегистрирован')) {
    return null
  }
  if (lineTrim.includes('[СЕССИЯ #')) return null
  if (lineTrim.includes('[ГРУППА #')) return null

  if (isError) {
    let errorKey = 'general_error'
    if (/connection refused/i.test(lineTrim)) errorKey = 'err_conn_refused'
    else if (/timeout/i.test(lineTrim)) errorKey = 'err_timeout'
    else errorKey = `general_error_${lineTrim.slice(0, 12)}`
    return { key: errorKey, message: lineTrim, priority: 99, isError: true }
  }

  return null
}

module.exports = { parseLibclientLine }
