'use strict'

const { execFile } = require('child_process')
const fs = require('fs')
const path = require('path')

const RULE_PREFIX = 'Silent VPN'
let ensurePromise = null

function runNetsh (args) {
  return new Promise((resolve) => {
    execFile('netsh', args, { windowsHide: true, timeout: 15000 }, () => resolve())
  })
}

async function upsertProgramRule (name, program, direction) {
  if (!program || !fs.existsSync(program)) return
  await runNetsh(['advfirewall', 'firewall', 'delete', 'rule', `name=${name}`])
  await runNetsh([
    'advfirewall', 'firewall', 'add', 'rule',
    `name=${name}`,
    `dir=${direction}`,
    'action=allow',
    `program=${program}`,
    'enable=yes',
    'profile=any'
  ])
}

/**
 * Ensure Windows Firewall already allows site-router / app / wdtt for the
 * current install path. Runs once per process; silent (no UI). Needs elevation
 * (app already requests requireAdministrator for VPN).
 */
function ensureSilentVpnFirewallAllow (resourcesPath, send) {
  if (process.platform !== 'win32') return Promise.resolve({ skipped: true })
  if (ensurePromise) return ensurePromise

  ensurePromise = (async () => {
    try {
      const res = path.resolve(resourcesPath || '')
      const siteRouter = path.join(res, 'wireguard', 'site-router.exe')
      const wdtt = path.join(res, 'wdtt-client.exe')
      // Packaged: .../resources -> parent has Silent VPN.exe
      // Dev: .../pc/resources -> look for electron / Silent VPN nearby
      const appCandidates = [
        path.join(path.dirname(res), 'Silent VPN.exe'),
        process.execPath
      ]
      const appExe = appCandidates.find((p) => p && fs.existsSync(p)) || process.execPath

      await upsertProgramRule(`${RULE_PREFIX} site-router`, siteRouter, 'in')
      await upsertProgramRule(`${RULE_PREFIX} site-router out`, siteRouter, 'out')
      await upsertProgramRule(`${RULE_PREFIX} app`, appExe, 'in')
      await upsertProgramRule(`${RULE_PREFIX} app out`, appExe, 'out')
      await upsertProgramRule(`${RULE_PREFIX} wdtt`, wdtt, 'in')
      await upsertProgramRule(`${RULE_PREFIX} wdtt out`, wdtt, 'out')

      if (typeof send === 'function') {
        send('[FW] Firewall allow rules ensured for site-router')
      }
      return {
        ok: true,
        siteRouter: fs.existsSync(siteRouter),
        app: fs.existsSync(appExe),
        wdtt: fs.existsSync(wdtt)
      }
    } catch (e) {
      if (typeof send === 'function') {
        send(`[FW] Firewall allow skipped: ${e.message || e}`)
      }
      return { ok: false, error: String(e && e.message ? e.message : e) }
    }
  })()

  return ensurePromise
}

module.exports = {
  ensureSilentVpnFirewallAllow,
  RULE_PREFIX
}
