import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeHiveCellLoads } from './hiveCellLoads.ts'

test('один пустой опрос не стирает метрики, третий показывает недоступность', () => {
  const live = [{ id: 'a', load: { cpu_percent: 12 } }]
  let misses: Record<string, number> = {}
  const first = mergeHiveCellLoads(live, [{ id: 'a' }], misses)
  assert.deepEqual(first.cells[0].load, { cpu_percent: 12 })
  misses = first.misses
  const second = mergeHiveCellLoads(first.cells, [{ id: 'a' }], misses)
  assert.deepEqual(second.cells[0].load, { cpu_percent: 12 })
  const third = mergeHiveCellLoads(second.cells, [{ id: 'a' }], second.misses)
  assert.equal(third.cells[0].load, undefined)
})
