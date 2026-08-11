/**
 * DNS туннеля: приоритет меню DNS → wg_dns с сервера → встроенный fallback.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { normalizeDnsValue, buildWgConfigFromApi } = require('../src/main/vpn/wireguard')

describe('normalizeDnsValue', () => {
  it('меню DNS важнее серверного', () => {
    assert.equal(normalizeDnsValue('77.88.8.8', '1.1.1.1, 1.0.0.1'), '1.1.1.1, 1.0.0.1')
  })

  it('без override берёт DNS сервера (в т.ч. фильтр угроз)', () => {
    assert.equal(normalizeDnsValue('10.66.66.1', ''), '10.66.66.1')
    assert.equal(normalizeDnsValue('77.88.8.8, 77.88.8.1', null), '77.88.8.8, 77.88.8.1')
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

  it('без override остаётся серверный DNS', () => {
    const conf = buildWgConfigFromApi({ ...base, wg_dns: '10.66.66.1' })
    assert.match(conf, /^DNS = 10\.66\.66\.1$/m)
  })
})
