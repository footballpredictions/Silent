import { traceUi } from './debugLog'

const TAG = 'SilentTrace'

function log(prefix: string, node: string, detail = '') {
  const body = detail ? `${node} | ${detail}` : node
  const msg = `${TAG} ${prefix} ${body}`
  if (import.meta.env.DEV) console.log(msg)
  traceUi(TAG, msg)
}

export const SessionTrace = {
  enter: (node: string, detail = '') => log('>>>', node, detail),
  exit: (node: string, detail = '') => log('<<<', node, detail),
  mark: (node: string, detail = '') => log('---', node, detail),
  wait: (node: string, detail = '') => log('...', node, detail),
  warn: (node: string, detail: string) => log('!!!', node, detail),
}
