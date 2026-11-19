const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const http = require('node:http')
const https = require('node:https')

const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
const start = source.indexOf('function backendHttpRequest(')
const end = source.indexOf('\nfunction isOlcrtc2ApiPath(', start)
const request = vm.runInNewContext(`${source.slice(start, end)}\nbackendHttpRequest`, {
  http, https, Buffer, URL, httpAgent: false, httpsAgent: false,
})

async function fixture(t, handler) {
  const server = http.createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)) })
  return { server, opts: { protocol: 'http', hostname: '127.0.0.1', port: server.address().port, path: '/fixture', timeout: 500 } }
}

test('real HTTP cancellation closes the losing socket rather than leaving it until timeout', async t => {
  let arrived, closed
  const seen = new Promise(resolve => { arrived = resolve })
  const gone = new Promise(resolve => { closed = resolve })
  const { opts } = await fixture(t, req => { req.on('close', closed); arrived() })
  const controller = new AbortController()
  const result = request({ ...opts, signal: controller.signal })
  const rejected = assert.rejects(result, error => error.code === 'ABORT_ERR')
  await seen
  controller.abort()
  await rejected
  await gone
})

test('real HTTP response loss reports that a POST may have been processed', async t => {
  let received = 0
  const { opts } = await fixture(t, req => { received++; req.socket.destroy() })
  await assert.rejects(request({ ...opts, method: 'POST', body: { fixture: true } }), error => error.requestDispatched === true)
  assert.equal(received, 1)
})

test('real connection refusal proves the mutation was never dispatched', async t => {
  const { server, opts } = await fixture(t, () => {})
  await new Promise(resolve => server.close(resolve))
  await assert.rejects(request({ ...opts, method: 'POST', body: {} }), error => error.code === 'ECONNREFUSED' && error.requestDispatched === false)
})

test('a truncated HTTP response rejects promptly instead of leaving API and startup waiting forever', async t => {
  const { opts } = await fixture(t, (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': 100 })
    res.write('{')
    setTimeout(() => res.destroy(), 10)
  })
  let timer
  const result = await Promise.race([
    request(opts).then(() => 'unexpected success', error => error.requestDispatched ? 'rejected' : 'missing dispatch status'),
    new Promise(resolve => { timer = setTimeout(() => resolve('stalled'), 200) }),
  ])
  clearTimeout(timer)
  assert.equal(result, 'rejected')
})

test('public HTTP timeout is labelled as public rather than as a failed tunnel API', async t => {
  const { opts } = await fixture(t, () => {})
  await assert.rejects(request({ ...opts, timeout: 30 }), /Public API timeout/)
})
