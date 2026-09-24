const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  RELEASES_JSON_URL,
  parseGithubOta,
  landingKey,
  otaDownloadCandidates,
} = require('../src/main/vpn/otaGithubDiscovery')

const JSON_BODY = JSON.stringify({
  api_base: 'https://89-125-188-100.nip.io',
  android: {
    version: '1.0.166',
    filename: 'SilentVPN-release-1.0.166.apk',
    size: 27778447,
    download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/SilentVPN-release-1.0.166.apk',
  },
  pc: {
    version: '1.0.166',
    filename: 'Silent.VPN.Setup.1.0.166.exe',
    size: 83072897,
    download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/Silent.VPN.Setup.1.0.166.exe',
  },
  linux: {
    version: '1.0.166',
    filename: 'Silent.VPN.Setup.1.0.166.deb',
    size: 118399176,
    download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/Silent.VPN.Setup.1.0.166.deb',
  },
})

describe('otaGithubDiscovery', () => {
  it('uses GitHub Pages, not the hive nip.io', () => {
    assert.equal(RELEASES_JSON_URL, 'https://silentvpn3.github.io/releases.json')
    assert.equal(RELEASES_JSON_URL.includes('nip.io'), false)
  })

  it('offers 1.0.166 to a 1.0.165 PC without asking the hive', () => {
    const got = parseGithubOta(JSON_BODY, 'pc', '1.0.165')
    assert.equal(got.kind, 'available')
    assert.equal(got.version, '1.0.166')
    assert.match(got.download_url, /github\.com\/silentvpn3/)
  })

  it('treats same version as current', () => {
    const got = parseGithubOta(JSON_BODY, 'pc', '1.0.166')
    assert.equal(got.kind, 'current')
    assert.equal(got.version, '1.0.166')
  })

  it('is unreadable on garbage so the client does not invent a hive check', () => {
    assert.equal(parseGithubOta(null, 'pc', '1.0.165').kind, 'unreadable')
    assert.equal(parseGithubOta('{', 'pc', '1.0.165').kind, 'unreadable')
  })

  it('mac arches: arm64 and x64 each get their own DMG', () => {
    const body = JSON.stringify({
      mac: {
        version: '1.0.168',
        filename: 'Silent.VPN.Setup.1.0.168-x64.dmg',
        size: 1,
        download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.168/Silent.VPN.Setup.1.0.168-x64.dmg',
        arches: {
          x64: {
            version: '1.0.168',
            filename: 'Silent.VPN.Setup.1.0.168-x64.dmg',
            size: 1,
            download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.168/Silent.VPN.Setup.1.0.168-x64.dmg',
          },
          arm64: {
            version: '1.0.168',
            filename: 'Silent.VPN.Setup.1.0.168-arm64.dmg',
            size: 2,
            download_url: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.168/Silent.VPN.Setup.1.0.168-arm64.dmg',
          },
        },
      },
    })
    const arm = parseGithubOta(body, 'mac', '1.0.167', 'arm64')
    const intel = parseGithubOta(body, 'mac', '1.0.167', 'x64')
    assert.equal(arm.kind, 'available')
    assert.match(arm.download_url, /-arm64\.dmg/)
    assert.match(intel.download_url, /-x64\.dmg/)
  })

  it('maps windows/darwin/tv onto landing keys and never prefers hive download', () => {
    assert.equal(landingKey('windows'), 'pc')
    assert.equal(landingKey('darwin'), 'mac')
    assert.equal(landingKey('android_tv'), 'android')
    const urls = otaDownloadCandidates({
      githubUrl: 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/app.exe',
      vpnUp: true,
      tunnelOrigin: 'http://10.66.66.1:8000',
      hiveDownloadPath: '/api/updates/download/pc',
    })
    assert.equal(urls[0].startsWith('https://github.com/'), true)
    assert.equal(urls.some((u) => u.includes('10.66.66.1')), false)
  })
})
