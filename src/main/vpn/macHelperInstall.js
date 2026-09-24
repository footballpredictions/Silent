'use strict'
/**
 * Установка/обновление LaunchDaemon helper из приложения (чистая установка из DMG:
 * первый VPN — bootstrap на экране входа, до него helper никто не ставил).
 *
 * Прошлые циклы пароля: весь скрипт строкой в AppleScript (-2741) и битый helper
 * (SyntaxError → daemon не стартует → снова пароль). Поэтому: максимум один запрос
 * за запуск, скрипт — временный файл, синтаксис helper проверяется до пароля.
 */
const fs = require('fs')
const os = require('os')
const path = require('path')
const { execFile } = require('child_process')
const { promisify } = require('util')

const execFileAsync = promisify(execFile)

let promptedThisRun = false

function buildInstallScript({ helperTmp, systemHelper, plistPath, label, sockPath }) {
  const runDir = path.dirname(sockPath)
  return `#!/bin/bash
set -e
mkdir -p /Library/PrivilegedHelperTools "${runDir}" /Library/LaunchDaemons
launchctl bootout system/${label} 2>/dev/null || true
pkill -f silent-vpn-wg-helper 2>/dev/null || true
rm -f "${sockPath}"
cp "${helperTmp}" "${systemHelper}"
chmod 755 "${systemHelper}"
chown root:wheel "${systemHelper}"
cat > "${plistPath}" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array>
<string>/usr/bin/python3</string>
<string>${systemHelper}</string>
<string>serve</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>${runDir}/helper.err</string>
<key>StandardOutPath</key><string>${runDir}/helper.out</string>
</dict></plist>
PLIST
chown root:wheel "${plistPath}"
chmod 644 "${plistPath}"
launchctl bootstrap system "${plistPath}" 2>/dev/null || true
launchctl enable system/${label} 2>/dev/null || true
launchctl kickstart -k system/${label} 2>/dev/null || true
for i in $(seq 1 20); do
  if /usr/bin/python3 -c "import socket,sys;s=socket.socket(socket.AF_UNIX);s.settimeout(0.3);s.connect(sys.argv[1])" "${sockPath}" 2>/dev/null; then
    exit 0
  fi
  sleep 0.25
done
nohup /usr/bin/python3 "${systemHelper}" serve >"${runDir}/helper.out" 2>"${runDir}/helper.err" &
sleep 1
exit 0
`
}

async function pythonAvailable() {
  try {
    await execFileAsync('/usr/bin/python3', ['-c', 'import sys'], { timeout: 15000 })
    return true
  } catch {
    return false
  }
}

/**
 * @returns {Promise<boolean>} true если скрипт установки отработал (пароль введён)
 */
async function installSystemHelperOnce({
  bundledHelper,
  systemHelper,
  plistPath,
  label,
  sockPath,
  reason = 'первый запуск',
  send,
}) {
  if (promptedThisRun) return false
  promptedThisRun = true

  if (!bundledHelper || !fs.existsSync(bundledHelper)) {
    send?.('[WG] Нет silent-wg-helper в приложении — переустановите Silent VPN', 'E')
    return false
  }
  if (!(await pythonAvailable())) {
    send?.(
      '[WG] Нет python3 для службы VPN. Установите Command Line Tools: в Terminal xcode-select --install',
      'E',
    )
    return false
  }

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-helper-'))
  try {
    const helperTmp = path.join(tmpDir, 'silent-wg-helper')
    const text = fs.readFileSync(bundledHelper, 'utf8').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
    fs.writeFileSync(helperTmp, text, { mode: 0o755 })
    try {
      await execFileAsync(
        '/usr/bin/python3',
        ['-c', 'import ast,sys;ast.parse(open(sys.argv[1]).read())', helperTmp],
        { timeout: 15000 },
      )
    } catch (e) {
      send?.(`[WG] silent-wg-helper битый (SyntaxError) — пароль не спрашиваю: ${String(e?.stderr || e?.message || e).slice(0, 160)}`, 'E')
      return false
    }

    const scriptPath = path.join(tmpDir, 'install.sh')
    fs.writeFileSync(
      scriptPath,
      buildInstallScript({ helperTmp, systemHelper, plistPath, label, sockPath }),
      { mode: 0o700 },
    )
    send?.(`[WG] Установка службы VPN (${reason}) — macOS один раз спросит пароль`)
    await execFileAsync(
      'osascript',
      [
        '-e',
        `do shell script "/bin/bash ${scriptPath}" with prompt "Silent VPN: установка службы VPN (один раз)" with administrator privileges`,
      ],
      { timeout: 180000 },
    )
    send?.('[WG] Служба VPN установлена')
    return true
  } catch (e) {
    const msg = String(e?.stderr || e?.message || e)
    if (/-128|cancel/i.test(msg)) {
      send?.('[WG] Установка службы VPN отменена — без неё VPN на Mac не работает', 'E')
    } else {
      send?.(`[WG] Установка службы VPN: ${msg.slice(0, 200)}`, 'E')
    }
    return false
  } finally {
    try { fs.rmSync(tmpDir, { recursive: true, force: true }) } catch { /* ignore */ }
  }
}

module.exports = {
  installSystemHelperOnce,
  buildInstallScript,
  _resetPromptForTests: () => { promptedThisRun = false },
}
