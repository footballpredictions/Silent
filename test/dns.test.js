/**
 * DNS туннеля: свой DNS → фильтр угроз 10.66.66.1 → как в 1.0.160 Cloudflare+Yandex.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { normalizeDnsValue, buildWgConfigFromApi } = require('../src/main/vpn/wireguard')

describe('normalizeDnsValue', () => {
  it('меню DNS важнее серверного', () => {
    assert.equal(normalizeDnsValue('77.88.8.8', '1.1.1.1, 1.0.0.1'), '1.1.1.1, 1.0.0.1')
  })

  it('фильтр угроз 10.66.66.1 не подменяется', () => {
    assert.equal(normalizeDnsValue('10.66.66.1', ''), '10.66.66.1')
  })

  it('серверный только-Яндекс как в 1.0.160 → Cloudflare+Yandex', () => {
    assert.equal(normalizeDnsValue('77.88.8.8, 77.88.8.1', null), '1.1.1.1, 1.0.0.1, 77.88.8.8')
  })

  it('без override и без серверного — встроенный список', () => {
    assert.equal(normalizeDnsValue('', ''), '1.1.1.1, 1.0.0.1, 77.88.8.8')
    assert.equal(normalizeDnsValue(undefined, undefined), '1.1.1.1, 1.0.0.1, 77.88.8.8')
  })

  it('нормализует разделители', () => {
    assert.equal(normalizeDnsValue('', '1.1.1.1;8.8.8.8'), '1.1.1.1, 8.8.8.8')
    assert.equal(normalizeDnsValue('', ' 9.9.9.9   1.1.1.1 '), '9.9.9.9, 1.1.1.1')
  })
})

describe('buildWgConfigFromApi', () => {
  const base = {
    wg_private_key: 'priv',
    server_public_key: 'pub',
    wg_address: '10.66.66.5/32',
    server_ip: '132.243.234.162',
    server_port: 56001,
  }

  it('свой DNS из меню попадает в конфиг', () => {
    const conf = buildWgConfigFromApi({ ...base, wg_dns: '77.88.8.8', dns_override: '9.9.9.9' })
    assert.match(conf, /^DNS = 9\.9\.9\.9$/m)
  })

  it('фильтр угроз остаётся серверным DNS', () => {
    const conf = buildWgConfigFromApi({ ...base, wg_dns: '10.66.66.1' })
    assert.match(conf, /^DNS = 10\.66\.66\.1$/m)
  })

  it('без override публичный серверный DNS как в 1.0.160', () => {
    const conf = buildWgConfigFromApi({ ...base, wg_dns: '77.88.8.8, 77.88.8.1' })
    assert.match(conf, /^DNS = 1\.1\.1\.1, 1\.0\.0\.1, 77\.88\.8\.8$/m)
  })
})
