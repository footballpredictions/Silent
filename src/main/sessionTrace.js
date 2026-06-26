/** ADB-style trace for main process — как Android SessionTrace.kt */

const TAG = 'SilentTrace'

const isDev = process.env.NODE_ENV === 'development'

function emit(prefix, node, detail, sendFn) {
  if (!isDev) return
  const body = detail ? `${node} | ${detail}` : node
  const msg = `${TAG} ${prefix} ${body}`
  sendFn?.({ tag: TAG, level: 'T', message: msg })
}

function createSessionTrace(sendFn) {
  return {
    enter: (node, detail = '') => emit('>>>', node, detail, sendFn),
    exit: (node, detail = '') => emit('<<<', node, detail, sendFn),
    mark: (node, detail = '') => emit('---', node, detail, sendFn),
    wait: (node, detail = '') => emit('...', node, detail, sendFn),
    warn: (node, detail) => emit('!!!', node, detail, sendFn),
  }
}

module.exports = { createSessionTrace, TAG }
