const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { PassThrough, Writable } = require('node:stream')
const cp = require('node:child_process')
const fs = require('node:fs')

function fixture() {
  const savedSpawn = cp.spawn, savedExec = cp.execFile, savedExists = fs.existsSync
  const sessions = []
  const state = { rejectPolicy: false, holdConfigure: false, spawnError: false, configured: null }
  cp.spawn = (exe, args, options) => {
    assert.ok(exe.endsWith('site-router.exe'))
    assert.deepEqual(args, [], 'private tunnel configuration must never be an argument')
    assert.equal(options.windowsHide, true)
    const child = new EventEmitter()
    child.pid = state.spawnError ? undefined : sessions.length + 100
    child.exitCode = null
    child.stdout = new PassThrough(); child.stderr = new PassThrough()
    child.messages = []
    let buffer = ''
    const exit = () => { if (child.exitCode != null) return; child.exitCode = 0; child.emit('exit', 0) }
    child.kill = exit
    child.stdin = new Writable({
      write(data, enc, done) {
        buffer += data
        while (buffer.includes('\n')) {
          const index = buffer.indexOf('\n')
          const message = JSON.parse(buffer.slice(0, index)); buffer = buffer.slice(index + 1)
          child.messages.push(message)
          queueMicrotask(() => {
            if (message.wireguard) child.stdout.write(JSON.stringify({ event: 'adapter', address: '10.0.0.2', mtu: 1200 }) + '\n')
            else if (message.op === 'stop') exit()
            else child.stdout.write(JSON.stringify({ id: message.id, ok: !(message.op === 'policy' && state.rejectPolicy) }) + '\n')
          })
        }
        done()
      },
    })
    sessions.push(child)
    if (state.spawnError) queueMicrotask(() => child.emit('error', new Error('spawn failed')))
    return child
  }
  cp.execFile = (exe, args, options, callback) => {
    assert.equal(exe, 'powershell.exe')
    assert.ok(args.at(-1).includes("Get-NetAdapter -Name 'wg-turn'"))
    if (state.holdConfigure) { state.configured?.(); state.releaseConfigure = () => callback(null, '') }
    else queueMicrotask(() => callback(null, ''))
  }
  fs.existsSync = p => String(p).endsWith('site-router.exe') || savedExists(p)
  const modulePath = require.resolve('../src/main/vpn/browserRouter')
  delete require.cache[modulePath]
  const router = require(modulePath)
  return { router, sessions, state, restore() { cp.spawn = savedSpawn; cp.execFile = savedExec; fs.existsSync = savedExists; delete require.cache[modulePath] } }
}

const options = { conf: 'private test configuration', gateway: { ifIndex: 47 }, resourcesPath: 'C:\\app\\resources', initialPolicy: { whitelist: true, targets: [], domains: [], excluded: [] } }

test('native lifecycle: live site/app updates merge, failure preserves old policy, stop is clean', async () => {
  const f = fixture()
  let failures = 0
  f.router.setFailureHandler(() => failures++)
  try {
    await f.router.start(options)
    assert.equal(f.router.isActive(), true)
    assert.equal(f.sessions[0].messages[0].wireguard, options.conf)
    await Promise.all([
      f.router.updatePolicy({ targets: ['8.8.8.8/32'] }),
      f.router.updatePolicy({ excluded: ['C:\\Games\\game.exe'] }),
    ])
    assert.deepEqual(f.router.policySnapshot().targets, ['8.8.8.8/32'])
    assert.deepEqual(f.router.policySnapshot().excluded, ['C:\\Games\\game.exe'])
    f.state.rejectPolicy = true
    await assert.rejects(f.router.updatePolicy({ targets: ['9.9.9.9/32'] }), /Не удалось/)
    assert.deepEqual(f.router.policySnapshot().targets, ['8.8.8.8/32'])
    await f.router.stop()
    assert.equal(f.router.isActive(), false)
    assert.equal(failures, 0)
    f.state.rejectPolicy = false
    await f.router.start(options)
    f.sessions[1].kill()
    assert.equal(f.router.isActive(), false)
    assert.equal(failures, 1)
  } finally { await f.router.stop(); f.restore() }
})

test('disconnect during adapter setup never resurrects a cancelled native session', async () => {
  const f = fixture()
  f.state.holdConfigure = true
  try {
    const configured = new Promise(resolve => { f.state.configured = resolve })
    const starting = f.router.start(options)
    const rejected = assert.rejects(starting, /отменён/)
    await configured
    await f.router.stop()
    f.state.releaseConfigure()
    await rejected
    assert.equal(f.router.isActive(), false)
    assert.equal(f.sessions[0].messages.some(m => m.op === 'start'), false)
  } finally { await f.router.stop(); f.restore() }
})

test('failed process creation rejects without waiting forever for an exit event', async () => {
  const f = fixture()
  f.state.spawnError = true
  try {
    await assert.rejects(f.router.start(options), /spawn failed/)
    assert.equal(f.router.isActive(), false)
  } finally { await f.router.stop(); f.restore() }
})

test('immediate disconnect cancels startup before any process can be spawned', async () => {
  const f = fixture()
  try {
    const starting = f.router.start(options)
    const rejected = assert.rejects(starting, /отменён/)
    await f.router.stop()
    await rejected
    assert.equal(f.sessions.length, 0)
    assert.equal(f.router.isActive(), false)
  } finally { await f.router.stop(); f.restore() }
})
