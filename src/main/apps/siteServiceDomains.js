// A site's resources can live outside its own DNS suffix. Keep these scoped to
// the selected service; do not turn all Google destinations into a site rule.
const youtube = {
  domains: ['youtube.com', 'googlevideo.com', 'ytimg.com', 'ggpht.com'],
  // Dynamic googlevideo hosts are learned from the browser's actual VPN DNS.
  // CDN roots themselves need not have A records. Seed common static hosts for
  // already-cached browser DNS, without treating optional seeds as unresolved rules.
  seeds: ['www.youtube.com', 'i.ytimg.com', 's.ytimg.com', 'yt3.ggpht.com'],
}
const youtubeNames = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'])

function serviceForDomain(rule) {
  const host = rule.toLowerCase().replace(/^\*\./, '')
  return youtubeNames.has(host) ? youtube : null
}

function browserDomains(rules) {
  return [...new Set(rules.flatMap(rule => [rule, ...(serviceForDomain(rule)?.domains || [])]))]
}

function browserLookupHosts(rule, hosts) {
  return [...new Set([...hosts, ...(serviceForDomain(rule)?.seeds || [])])]
}

module.exports = { browserDomains, browserLookupHosts }
