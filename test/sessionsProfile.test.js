const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function fixture() {
  const source = fs.readFileSync(require.resolve('../src/renderer/pages/MainScreen.tsx'), 'utf8')
  const start = source.indexOf('  const fetchProfile = useCallback(')
  const end = source.indexOf('\n\n  const stopPaymentPoll', start)
  const code = ts.transpileModule(source.slice(start, end), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
  const requests = []
  let profile = { devices: [{ id: 'current' }] }
  const context = {
    useCallback: fn => fn, profileFetchVersionRef: { current: 0 },
    profileRequestVersionRef: { current: 0 }, profileMutationVersionRef: { current: 0 },
    api: { get: () => new Promise((resolve, reject) => requests.push({ resolve, reject })) },
    applyServerProfile: value => { profile = value }, setProfile: value => { profile = value },
    setSessionsError() {}, saveVkUserId() {}, getCachedProfile: () => ({ devices: [{ id: 'cached' }] }),
  }
  const fetch = vm.runInNewContext(`${code}\nfetchProfile`, context)
  return { fetch, requests, context, get profile() { return profile } }
}

test('older sessions response cannot overwrite a newer profile', async () => {
  const f = fixture()
  const first = f.fetch(), second = f.fetch()
  f.requests[1].resolve({ data: { devices: [{ id: 'new' }] } }); await second
  f.requests[0].resolve({ data: { devices: [{ id: 'old' }] } }); await first
  assert.equal(f.profile.devices[0].id, 'new')
})

test('failed session refresh preserves the current profile instead of replacing it with cache', async () => {
  const f = fixture()
  const pending = f.fetch()
  f.requests[0].reject(Error('WAN blocked')); await pending
  assert.equal(f.profile.devices[0].id, 'current')
})

test('profile requested before a session mutation cannot restore deleted devices', async () => {
  const f = fixture()
  const pending = f.fetch()
  f.context.profileFetchVersionRef.current++
  f.requests[0].resolve({ data: { devices: [{ id: 'deleted' }] } }); await pending
  assert.equal(f.profile.devices[0].id, 'current')
})
