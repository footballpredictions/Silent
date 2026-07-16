/** VK ID: .com часто тормозит/ломается при DPI — грузим .ru. */
function normalizeCaptchaRedirectUri(uri) {
  let u = String(uri || '').trim()
  if (!u) return u
  return u
    .replace(/\/\/id\.vk\.com\b/gi, '//id.vk.ru')
    .replace(/\/\/login\.vk\.com\b/gi, '//login.vk.ru')
    .replace(/\/\/oauth\.vk\.com\b/gi, '//oauth.vk.ru')
    .replace(/([?&]domain=)vk\.com\b/gi, '$1vk.ru')
}

module.exports = { normalizeCaptchaRedirectUri }
