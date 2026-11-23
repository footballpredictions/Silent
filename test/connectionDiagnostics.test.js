const assert = require('node:assert/strict')
const test = require('node:test')
const { getWindowsConnectionHints } = require('../src/main/vpn/connectionDiagnostics')

test('Windows diagnostics report each observed condition after a failed connection', async () => {
  const hints = await getWindowsConnectionHints({
    wireGuardApplied: false,
    run: async (command, args, options) => {
      assert.equal(command, 'powershell.exe')
      assert.ok(args.includes('-NonInteractive'))
      assert.ok(options.timeout > 0)
      return { stdout: JSON.stringify({ otherVpn: true, silentServiceRunning: true, dohConfigured: true }) }
    },
  })
  assert.equal(hints.length, 3)
  assert.match(hints[0], /VPN-подключение/)
  assert.match(hints[1], /WireGuardTunnel\$wg-turn/)
  assert.match(hints[2], /DNS-over-HTTPS/)
})

test('the expected running WireGuard service does not suggest a stale session', async () => {
  const hints = await getWindowsConnectionHints({
    wireGuardApplied: true,
    run: async () => ({ stdout: '{"silentServiceRunning":true}' }),
  })
  assert.deepEqual(hints, [])
})

test('an unavailable Windows probe does not produce a connection warning', async () => {
  const hints = await getWindowsConnectionHints({
    wireGuardApplied: false,
    run: async () => { throw new Error('PowerShell unavailable') },
  })
  assert.deepEqual(hints, [])
})
