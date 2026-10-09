import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('../src/adminVersion.ts', import.meta.url), 'utf8')
const compiled = ts.transpile(source, { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 })
const { watchAdminVersion } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

const settle = async () => {
  await new Promise(resolve => setImmediate(resolve))
  await new Promise(resolve => setImmediate(resolve))
}

function environment({ storage = new Map(), url = 'https://admin.test/hive', disabledStorage = false } = {}) {
  const listeners = new Map()
  const env = { requests: [], reloads: 0, replacements: [], reply: { version: 'v1', assets: ['/assets/app-v1.js'] } }
  const listen = (type, callback) => listeners.set(type, callback)
  const location = {
    href: url,
    reload: () => { env.reloads++ },
    replace: value => { location.href = String(value); env.replacements.push(location.href) },
  }
  Object.assign(globalThis, {
    location,
    document: {
      visibilityState: 'visible',
      querySelectorAll: () => [{ getAttribute: name => name === 'src' ? '/assets/app-v1.js' : null }],
      addEventListener: listen,
    },
    window: { addEventListener: listen, setTimeout, clearTimeout },
    sessionStorage: {
      getItem: key => { if (disabledStorage) throw new Error('disabled'); return storage.get(key) },
      setItem: (key, value) => { if (disabledStorage) throw new Error('disabled'); storage.set(key, value) },
      removeItem: key => { if (disabledStorage) throw new Error('disabled'); storage.delete(key) },
    },
    fetch: async (path, options) => {
      env.requests.push({ path, options })
      if (env.pending) return env.pending
      if (env.reply instanceof Error) throw env.reply
      return { ok: env.status !== 503, json: async () => env.reply }
    },
  })
  env.emit = (type, event = {}) => listeners.get(type)?.(event)
  return env
}

test('current build stays open and uses an uncached version probe', async () => {
  const env = environment()
  watchAdminVersion()
  await settle()
  assert.equal(env.requests.length, 1)
  assert.equal(env.requests[0].options.cache, 'no-store')
  env.emit('pageshow', { persisted: true })
  await settle()
  assert.equal(env.reloads, 0)
})

test('restored old build reloads exactly once for the new publication', async () => {
  const storage = new Map()
  const env = environment({ storage })
  watchAdminVersion()
  await settle()
  env.reply = { version: 'v2', assets: ['/assets/app-v2.js'] }
  env.emit('pageshow', { persisted: true })
  await settle()
  assert.equal(env.reloads, 1)
  const reopened = environment({ storage })
  reopened.reply = env.reply // A broken proxy still serves the old entry after reload.
  watchAdminVersion()
  await settle()
  assert.equal(reopened.reloads, 0)
})

test('offline or 503 probe preserves the app and retries on return', async () => {
  for (const failure of ['offline', '503']) {
    const env = environment()
    if (failure === 'offline') env.reply = new Error('offline')
    else env.status = 503
    watchAdminVersion()
    await settle()
    assert.equal(env.reloads, 0)
    env.status = 200
    env.reply = { version: 'v2', assets: ['/assets/app-v2.js'] }
    env.emit('visibilitychange')
    await settle()
    assert.equal(env.reloads, 1)
  }
})

test('overlapping resume and focus events share one in-flight probe', async () => {
  const env = environment()
  let complete
  env.pending = new Promise(resolve => { complete = resolve })
  watchAdminVersion()
  env.emit('focus')
  env.emit('visibilitychange')
  env.emit('pageshow', { persisted: true })
  assert.equal(env.requests.length, 1)
  complete({ ok: true, json: async () => env.reply })
  await settle()
  assert.equal(env.reloads, 0)
})

test('disabled storage bounds reloads through the URL without clearing login', async () => {
  const env = environment({ disabledStorage: true })
  env.reply = { version: 'v2', assets: ['/assets/app-v2.js'] }
  watchAdminVersion()
  await settle()
  assert.equal(env.replacements.length, 1)
  const reopened = environment({ disabledStorage: true, url: location.href })
  reopened.reply = env.reply
  watchAdminVersion()
  await settle()
  assert.equal(reopened.replacements.length, 0)
})

test('malformed or incomplete publication never reloads', async () => {
  for (const assets of [[], ['https://external.test/app.js'], [null]]) {
    const env = environment()
    env.reply = { version: 'v2', assets }
    watchAdminVersion()
    await settle()
    assert.equal(env.reloads, 0)
  }
})
