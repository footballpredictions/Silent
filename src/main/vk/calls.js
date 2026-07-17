const VK_API_VERSION = '5.199'

function extractHash(joinLink) {
  const m = String(joinLink || '').match(/\/join\/([A-Za-z0-9_-]+)/)
  if (m) return m[1]
  const s = String(joinLink || '').trim()
  if (s.length >= 8 && /^[A-Za-z0-9_-]+$/.test(s)) return s
  return null
}

async function vkGet(url) {
  const res = await fetch(url)
  const data = await res.json()
  return data
}

async function createCallHash(accessToken) {
  const url = `https://api.vk.ru/method/calls.start?access_token=${encodeURIComponent(accessToken)}&v=${VK_API_VERSION}&client_id=6287487`
  const data = await vkGet(url)
  if (data.error) {
    const code = data.error.error_code
    const msg = data.error.error_msg || 'calls.start error'
    throw new Error(code ? `[${code}] ${msg}` : msg)
  }
  const joinLink = data.response?.join_link || ''
  const hash = extractHash(joinLink)
  if (!hash) throw new Error('calls.start без join_link')
  return hash
}

async function resolveUserId(accessToken) {
  const url = `https://api.vk.ru/method/users.get?access_token=${encodeURIComponent(accessToken)}&v=${VK_API_VERSION}`
  const data = await vkGet(url)
  if (data.error) throw new Error(data.error.error_msg || 'users.get error')
  const id = data.response?.[0]?.id
  if (!id) throw new Error('users.get пустой')
  return id
}

module.exports = { createCallHash, resolveUserId, extractHash }
