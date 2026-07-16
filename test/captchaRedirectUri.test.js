const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const { normalizeCaptchaRedirectUri } = require('../src/main/vk/captchaRedirectUri')

describe('normalizeCaptchaRedirectUri', () => {
  it('rewrites id.vk.com host and domain=vk.com to .ru', () => {
    const raw =
      'https://id.vk.com/not_robot_captcha?domain=vk.com&session_token=abc&variant=popup'
    const out = normalizeCaptchaRedirectUri(raw)
    assert.match(out, /^https:\/\/id\.vk\.ru\//)
    assert.match(out, /[?&]domain=vk\.ru\b/)
    assert.doesNotMatch(out, /domain=vk\.com/)
  })

  it('keeps id.vk.ru and only fixes domain param', () => {
    const raw = 'https://id.vk.ru/not_robot_captcha?domain=vk.com&blank=1'
    const out = normalizeCaptchaRedirectUri(raw)
    assert.equal(out, 'https://id.vk.ru/not_robot_captcha?domain=vk.ru&blank=1')
  })
})
