'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('firewallAllow module exports ensure helper', () => {
  const mod = require('../src/main/firewallAllow')
  assert.equal(typeof mod.ensureSilentVpnFirewallAllow, 'function')
  assert.equal(mod.RULE_PREFIX, 'Silent VPN')
})

test('installer.nsh creates permanent site-router firewall rules', () => {
  const nsh = fs.readFileSync(path.join(__dirname, '../build/installer.nsh'), 'utf8')
  assert.match(nsh, /Silent VPN site-router/)
  assert.match(nsh, /site-router\.exe/)
  assert.match(nsh, /CustomSilentFirewallAdd/)
  assert.match(nsh, /customUnInstall/)
  assert.match(nsh, /profile=any/)
  assert.match(nsh, /WireGuard repair done/)
  assert.match(nsh, /silentVpnWipeRuntime/)
  assert.match(nsh, /post-install\.stamp/)
})

test('browserRouter ensures firewall before spawning site-router', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/main/vpn/browserRouter.js'), 'utf8')
  assert.match(src, /ensureSilentVpnFirewallAllow/)
  const ensureAt = src.indexOf('ensureSilentVpnFirewallAllow')
  const spawnAt = src.indexOf("spawn(exe")
  assert.ok(ensureAt > 0 && spawnAt > ensureAt, 'firewall allow must run before spawn')
})
