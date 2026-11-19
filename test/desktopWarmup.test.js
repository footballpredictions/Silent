const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

test('overlapping browsing warmups share one bounded HEAD pass and never download page bodies', async () => {
  const code = ts.transpileModule(fs.readFileSync(require.resolve('../src/renderer/warmupBrowsingPath.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}, calls = [], pending = []
  let nativeCalls = 0
  vm.runInNewContext(code, {
    exports, AbortController,
    window: { setTimeout, electronAPI: { warmupTelegramPath: async () => { nativeCalls++ } } },
    clearTimeout,
    fetch: (url, opts) => { calls.push({ url, ...opts }); return new Promise(resolve => pending.push(resolve)) },
  })
  const passes = [exports.warmupBrowsingPath(), exports.warmupBrowsingPath(), exports.warmupBrowsingPath()]
  for (let i = 0; i < 100; i++) {
    for (const resolve of pending.splice(0)) resolve({})
    await new Promise(resolve => setImmediate(resolve))
  }
  await Promise.all(passes)
  assert.equal(nativeCalls, 1, 'three callers must not each open native Telegram sockets')
  assert.equal(new Set(calls.map(c => c.url)).size, calls.length, 'no duplicate requests during one pass')
  assert.ok(calls.every(c => c.method === 'HEAD'), 'warmup must not download Telegram/YouTube page bodies')
})

test('native warmup runs at most once per healthy VPN session and waits for sufficient relays', () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const fn = source.match(/function maybeWarmupTelegram\(sendLogFn, opts = \{\}\) \{[\s\S]*?\n\}/)[0]
  let calls = 0
  const state = {
    vpnSessionActive: true, vpnBootstrapMode: false, vpnOlcrtcMode: false,
    activeWorkerCount: 1, WORKERS_PER_GROUP: 9, telegramWarmupMinWorkersDone: false,
    warmupTelegramTcp: () => { calls++ },
  }
  const warmup = vm.runInNewContext(`(${fn})`, state)
  warmup(() => {}, { force: true })
  assert.equal(calls, 0, 'do not force warmup through one relay')
  state.activeWorkerCount = 63
  for (let i = 0; i < 8; i++) warmup(() => {}, { force: true })
  assert.equal(calls, 1)
  state.telegramWarmupMinWorkersDone = false
  warmup(() => {})
  assert.equal(calls, 2, 'a new transport may warm its own path once')
})
