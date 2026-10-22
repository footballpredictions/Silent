const fs = require('fs')

function linuxUpdateFormat(header) {
  if (header.subarray(0, 4).equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46]))) return 'appimage'
  const member = header.toString('ascii', 8, 24).trim().replace(/\/$/, '').trim()
  if (header.toString('ascii', 0, 8) === '!<arch>\n' && member === 'debian-binary' &&
      header.toString('ascii', 66, 68) === '`\n' &&
      Number(header.toString('ascii', 56, 66).trim()) === 4 &&
      header.toString('ascii', 68, 72) === '2.0\n') return 'deb'
  throw new Error('Файл повреждён (это не Linux DEB или AppImage)')
}

function readLinuxUpdateFormat(filename) {
  const descriptor = fs.openSync(filename, 'r')
  try {
    const header = Buffer.alloc(72)
    fs.readSync(descriptor, header, 0, header.length, 0)
    return linuxUpdateFormat(header)
  } finally { fs.closeSync(descriptor) }
}

function shellQuote(value) {
  return "'" + String(value).replace(/'/g, "'\"'\"'") + "'"
}

function linuxUpdateScript({ format, setup, current = '', logPath, elevated = false, launcher = '/usr/bin/silent-vpn', previousLauncher = launcher }) {
  const lines = ['#!/bin/sh', `log=${shellQuote(logPath)}`, `setup=${shellQuote(setup)}`, 'printf "waiting\\n" > "$log"', 'sleep 3']
  if (format === 'deb') {
    const install = elevated ? '/usr/bin/dpkg' : 'pkexec /usr/bin/dpkg'
    lines.push(
      `if ${install} -i "$setup" >> "$log" 2>&1; then`,
      '  unset APPIMAGE APPDIR',
      '  printf "installed\\n" >> "$log"',
      `  nohup ${shellQuote(launcher)} >/dev/null 2>&1 &`,
      'else',
      '  printf "installation failed or cancelled\\n" >> "$log"',
      '  if command -v notify-send >/dev/null 2>&1; then notify-send "Silent VPN" "Обновление не установлено. Подробности: $log"; fi',
      `  nohup ${shellQuote(previousLauncher)} >/dev/null 2>&1 &`,
      'fi',
    )
  } else if (format === 'appimage') {
    lines.push('chmod +x "$setup"')
    if (current) {
      lines.push(`current=${shellQuote(current)}`, 'if [ -f "$current" ]; then cp -f "$setup" "$current" && chmod +x "$current"; fi', 'nohup "$current" >/dev/null 2>&1 &')
    } else {
      lines.push('nohup "$setup" >/dev/null 2>&1 &')
    }
  } else {
    throw new Error('Неизвестный формат Linux-обновления')
  }
  lines.push('rm -f "$0"', '')
  return lines.join('\n')
}

module.exports = { linuxUpdateFormat, readLinuxUpdateFormat, linuxUpdateScript }
