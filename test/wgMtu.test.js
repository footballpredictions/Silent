const test = require('node:test')
const assert = require('node:assert/strict')
const { resolveWgMtu } = require('../src/main/vpn/wgMtu')

test('server profile overrides slot and IP in both directions', () => {
  assert.equal(resolveWgMtu({ selected_server: 'server1', wg_mtu: 1420 }), 1420)
  assert.equal(resolveWgMtu({ selected_server: 'server3', server_ip: '78.17.74.27', wg_mtu: 1200 }), 1200)
})

test('missing or invalid metadata preserves old client behaviour', () => {
  for (const wg_mtu of [undefined, null, 0, -1, '1420', 9000, 1200.5]) {
    assert.equal(resolveWgMtu({ selected_server: 'server3', wg_mtu }), 1420)
    assert.equal(resolveWgMtu({ selected_server: 'server1', wg_mtu }), 1200)
  }
})
