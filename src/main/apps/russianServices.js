const fs = require('fs')
const path = require('path')
const http = require('http')
const https = require('https')
const bundled = require('./russian-services-policy.json')

const ENDPOINTS = ['https://89-125-188-100.nip.io', 'http://87.58.213.193:9100',
  'http://78.17.74.27:9100', 'http://192.177.26.38:9100', 'http://89.37.192.241:9100']
const DELIVERY = { WAITING: 'waiting', LOADING: 'loading', RECEIVED: 'received', FAILED: 'failed' }

function validPolicy(value) {
  const domains = list => Array.isArray(list) && list.length <= 2000 && list.every(s =>
    typeof s === 'string' && s.length <= 253 && s.split('.').every(label =>
      /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)))
  return value?.schema_version === 1 && /^[a-f0-9]{64}$/.test(value.revision) &&
    domains(value.direct_domains) && domains(value.vpn_domains)
}
function download(url) {
  return new Promise((resolve, reject) => {
    const request = (url.startsWith('https:') ? https : http).get(url, response => {
      if (response.statusCode !== 200) { response.resume(); reject(new Error(`HTTP ${response.statusCode}`)); return }
      const chunks = []; let length = 0
      response.on('data', chunk => {
        length += chunk.length
        if (length > 262144) request.destroy(new Error('Policy too large'))
        else chunks.push(chunk)
      })
      response.on('error', reject)
      response.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))) } catch (error) { reject(error) }
      })
    })
    // A total deadline also bounds DNS/connect, unlike a socket idle timeout.
    const deadline = setTimeout(() => request.destroy(new Error('Policy timeout')), 2500)
    request.on('close', () => clearTimeout(deadline))
    request.on('error', reject)
  })
}
class RussianServices {
  constructor(directory, fetchPolicy = download) {
    this.file = path.join(directory, 'russian-services.json')
    this.fetchPolicy = fetchPolicy
    this.active = false
    this.policy = bundled
    this.delivery = DELIVERY.WAITING
    this.receivedRevision = null
    this.fetching = false
    try {
      const value = JSON.parse(fs.readFileSync(this.file, 'utf8'))
      this.active = value.enabled === true
      if (validPolicy(value.policy)) this.policy = value.policy
    } catch { /* Default OFF and bundled policy work offline on first run. */ }
  }
  enabled() { return this.active }
  deliveryStatus() { return this.active ? this.delivery : DELIVERY.WAITING }
  snapshot() { return { ...this.policy, enabled: this.active, delivery: this.deliveryStatus() } }
  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true })
    const temporary = this.file + '.tmp'
    fs.writeFileSync(temporary, JSON.stringify({ enabled: this.active, policy: this.policy }), 'utf8')
    fs.renameSync(temporary, this.file)
  }
  setEnabled(enabled) {
    const previous = this.active
    this.active = enabled === true
    this.receivedRevision = null
    this.delivery = DELIVERY.WAITING
    try { this.save() } catch (error) { this.active = previous; throw error }
  }
  beginRefresh() {
    if (!this.active) return
    this.receivedRevision = null
    this.delivery = DELIVERY.LOADING
  }
  markApplied() {
    if (this.active && this.receivedRevision) this.delivery = DELIVERY.RECEIVED
  }
  markFailed() {
    if (this.active && this.delivery !== DELIVERY.RECEIVED) this.delivery = DELIVERY.FAILED
  }
  tunnelStopped() {
    if (this.delivery === DELIVERY.RECEIVED) this.delivery = DELIVERY.WAITING
  }
  async refresh() {
    if (!this.active || this.fetching) return false
    this.fetching = true
    this.beginRefresh()
    try {
      for (const base of ENDPOINTS) {
        try {
          const policy = await this.fetchPolicy(base + '/api/vpn/routing-policy')
          if (!validPolicy(policy)) continue
          const previousRevision = this.policy.revision
          if (policy.revision !== previousRevision) {
            const previous = this.policy
            this.policy = policy
            try { this.save() } catch (error) { this.policy = previous; throw error }
          }
          this.receivedRevision = policy.revision
          return policy.revision !== previousRevision
        } catch { /* Keep last good cache, try a separate public endpoint. */ }
      }
      this.markFailed()
      return false
    } finally { this.fetching = false }
  }
}
let current = null
function configure(directory) {
  if (!current || current.file !== path.join(directory, 'russian-services.json')) current = new RussianServices(directory)
  return current
}
module.exports = {
  RussianServices, validPolicy, DELIVERY, configure,
  supported: () => process.platform === 'win32',
  enabled: () => process.platform === 'win32' && current?.enabled() === true,
  snapshot: () => current?.snapshot() || { ...bundled, enabled: false, delivery: DELIVERY.WAITING },
}
