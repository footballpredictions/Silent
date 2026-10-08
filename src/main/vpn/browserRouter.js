/** Windows per-process WireGuard router. Private configuration travels only over stdin. */
const { spawn, execFile } = require('child_process')
const { promisify } = require('util')
const path = require('path')
const fs = require('fs')
const readline = require('readline')
const execFileAsync = promisify(execFile)

let current = null
let nextId = 0
let policy = { whitelist: false, targets: [], domains: [], excluded: [], dns: [] }
let failureHandler = () => {}
let policyUpdates = Promise.resolve()
let generation = 0

function isActive() { return !!(current?.ready && current.child.exitCode == null && !current.stopping) }
function setFailureHandler(handler) { failureHandler = handler }
function request(session, op, payload = {}, timeout = 5000) {
  if (session.stopping || session.child.exitCode != null) return Promise.reject(new Error('Маршрутизатор остановлен'))
  const id = ++nextId
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { session.pending.delete(id); reject(new Error('Маршрутизатор не ответил')) }, timeout)
    session.pending.set(id, { resolve, reject, timer })
    session.child.stdin.write(JSON.stringify({ id, op, ...payload }) + '\n', error => {
      if (!error || !session.pending.has(id)) return
      clearTimeout(timer); session.pending.delete(id); reject(error)
    })
  })
}

function policySnapshot() { return { ...policy } }
async function updatePolicy(patch) {
  const result = policyUpdates.then(() => updatePolicyUnlocked(patch))
  policyUpdates = result.catch(() => {})
  return result
}
async function updatePolicyUnlocked(patch) {
  const next = { ...policy, ...patch }
  const session = current
  if (isActive()) {
    try {
      const result = await request(session, 'policy', { policy: next })
      if (!result.ok) throw new Error('Не удалось применить правила браузера')
    } catch (error) {
      // Disconnect/start owns a newer session; keep the saved policy for next start.
      if (current === session && !session.stopping) throw error
    }
  }
  policy = next
  return { ok: true }
}

// The name is fixed, and every interpolated value below is validated before use.
function adapterScript(address, mtu) {
  if (!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(address) || !Number.isInteger(mtu) || mtu < 576 || mtu > 9000) {
    throw new Error('Неверные параметры адаптера')
  }
  return `$ErrorActionPreference='Stop'
    $a=Get-NetAdapter -Name 'wg-turn' -ErrorAction Stop
    Set-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -Dhcp Disabled -InterfaceMetric 5
    Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '${address}' } | Remove-NetIPAddress -Confirm:$false
    if (-not (Get-NetIPAddress -InterfaceIndex $a.ifIndex -IPAddress '${address}' -ErrorAction SilentlyContinue)) {
      New-NetIPAddress -InterfaceIndex $a.ifIndex -IPAddress '${address}' -PrefixLength 32 -PolicyStore ActiveStore | Out-Null
    }
    Set-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -NlMtuBytes ${mtu}
    foreach ($prefix in @('0.0.0.0/1','128.0.0.0/1')) {
      if (-not (Get-NetRoute -InterfaceIndex $a.ifIndex -DestinationPrefix $prefix -ErrorAction SilentlyContinue)) {
        New-NetRoute -InterfaceIndex $a.ifIndex -DestinationPrefix $prefix -NextHop '0.0.0.0' -RouteMetric 5 -PolicyStore ActiveStore | Out-Null
      }
    }`
}

async function start({ conf, gateway, resourcesPath, initialPolicy, send, isCancelled = () => false }) {
  const run = ++generation
  await stopCurrent()
  await policyUpdates
  if (run !== generation || isCancelled()) throw new Error('Запуск VPN отменён')
  if (!gateway?.ifIndex) throw new Error('Не найден физический интерфейс')
  policy = { ...policy, ...initialPolicy }
  const exe = path.join(resourcesPath, 'wireguard', 'site-router.exe')
  if (!fs.existsSync(exe)) throw new Error('В сборке отсутствует маршрутизатор сайтов')
  const child = spawn(exe, [], { cwd: path.dirname(exe), windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  const session = { child, pending: new Map(), ready: false, stopping: false }
  current = session
  let resolveAdapter, rejectAdapter
  const adapterReady = new Promise((resolve, reject) => { resolveAdapter = resolve; rejectAdapter = reject })
  const timer = setTimeout(() => rejectAdapter(new Error('Не удалось создать VPN-адаптер')), 15000)
  const rejectPending = error => {
    rejectAdapter(error)
    for (const p of session.pending.values()) { clearTimeout(p.timer); p.reject(error) }
    session.pending.clear()
  }
  const lines = readline.createInterface({ input: child.stdout })
  lines.on('line', line => {
    let message
    try { message = JSON.parse(line) } catch { return }
    if (message.event === 'adapter') resolveAdapter(message)
    const pending = session.pending.get(message.id)
    if (pending) { clearTimeout(pending.timer); session.pending.delete(message.id); pending.resolve(message) }
  })
  // Native errors may contain network addresses, but never configuration/key material.
  child.stderr.on('data', data => send?.('[Sites] ' + String(data).trim().slice(0, 250)))
  child.stdin.on('error', error => rejectPending(error))
  child.on('error', rejectPending)
  child.on('exit', () => {
    const wasReady = session.ready
    session.ready = false
    rejectPending(new Error('Маршрутизатор сайтов завершился'))
    lines.close()
    if (current === session) {
      current = null
      if (wasReady && !session.stopping) failureHandler()
    }
  })
  try {
    child.stdin.write(JSON.stringify({ wireguard: conf, physicalIndex: gateway.ifIndex, policy }) + '\n')
    const adapter = await adapterReady
    await execFileAsync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', adapterScript(adapter.address, adapter.mtu)], { windowsHide: true, timeout: 20000 })
    if (current !== session || session.stopping || isCancelled()) throw new Error('Запуск VPN отменён')
    const result = await request(session, 'start')
    if (!result.ok) throw new Error('Маршрутизатор не запустился')
    session.ready = true
    await updatePolicy({})
    if (current !== session || session.stopping || isCancelled()) throw new Error('Запуск VPN отменён')
    send?.('[Sites] Браузеры и приложения маршрутизируются независимо')
    return true
  } catch (error) {
    if (current === session) await stop()
    throw error
  } finally { clearTimeout(timer) }
}

async function stop() {
  generation++
  await stopCurrent()
}
async function stopCurrent() {
  const session = current
  if (!session) return
  session.stopping = true
  session.ready = false
  if (!session.child.pid || session.child.exitCode != null) {
    if (current === session) current = null
    return
  }
  const exited = new Promise(resolve => {
    if (session.child.exitCode != null) return resolve()
    session.child.once('exit', resolve)
  })
  session.child.stdin.end(JSON.stringify({ op: 'stop' }) + '\n')
  const timer = setTimeout(() => session.child.kill(), 3000)
  try { await exited } finally { clearTimeout(timer); if (current === session) current = null }
}

module.exports = { start, stop, isActive, updatePolicy, policySnapshot, setFailureHandler, adapterScript }
