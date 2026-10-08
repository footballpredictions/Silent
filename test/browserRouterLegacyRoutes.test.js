const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { promisify } = require('node:util')

test('real browser policy removes stale physical site routes before native ACK, preserving transport', async () => {
  const events = []
  const execFile = () => {}
  execFile[promisify.custom] = async (_exe, args) => {
    events.push({ script: args.at(-1) })
    return { stdout: '1' }
  }
  const module = { exports: {} }
  const source = fs.readFileSync(require.resolve('../src/main/vpn/browserRouter'), 'utf8')
  vm.runInNewContext(source + `
    current = {ready:true, stopping:false, gateway:{ifIndex:47,nextHop:'192.168.1.1'}, protectedTargets:['192.177.26.38/32'], pending:new Map(), child:{exitCode:null,stdin:{write(line){
      const message=JSON.parse(line); events.push({ack:message.policy.targets});
      const p=current.pending.get(message.id);clearTimeout(p.timer);current.pending.delete(message.id);p.resolve({ok:true});
    }}}};`, {
    module, events, setTimeout, clearTimeout,
    require(name) { return name === 'child_process' ? { execFile } : require(name) },
  })
  await module.exports.updatePolicy({ whitelist:true, targets:['188.40.167.81/32','192.177.26.38/32'], domains:['2ip.io'] })
  assert.equal(events.length, 2, 'cleanup must run before applying the native policy')
  assert.match(events[0].script, /188\.40\.167\.81\/32/)
  assert.doesNotMatch(events[0].script, /192\.177\.26\.38/)
  assert.match(events[0].script, /Remove-NetRoute/)
  assert.match(events[0].script, /RouteMetric -le 1/)
  assert.match(events[0].script, /ActiveStore/)
  assert.match(events[0].script, /InterfaceIndex -eq 47/)
  assert.deepEqual(Array.from(events[1].ack), ['188.40.167.81/32','192.177.26.38/32'])
})
