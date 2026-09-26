import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { bumpIncidentGen, shouldApplyIncidentList } from './incidentListGuard.ts'

function paintLate(apply: (started: number, current: number) => boolean) {
  let gen = 0
  const db = ['старый']
  let shown = ['старый']

  const earlyGen = gen
  const earlySnap = db.slice()

  gen = bumpIncidentGen(gen)
  shown = []

  const midGen = gen
  const midSnap = db.slice()

  db.length = 0
  gen = bumpIncidentGen(gen)
  const confirmGen = gen
  const confirmSnap = db.slice()

  if (apply(confirmGen, gen)) shown = confirmSnap
  if (apply(earlyGen, gen)) shown = earlySnap
  if (apply(midGen, gen)) shown = midSnap
  return shown
}

test('старый ответ опроса, пришедший после очистки, не возвращает список', () => {
  assert.deepEqual(paintLate(shouldApplyIncidentList), [])
  assert.deepEqual(paintLate(() => true), ['старый'])
})

test('кнопка очистки сдвигает поколение до запроса и после удаления', () => {
  const src = readFileSync(new URL('./pages/HivePage.tsx', import.meta.url), 'utf8')
  const body = src.slice(src.indexOf('const clearIncidents'), src.indexOf('const queenCell'))
  assert.equal(body.split('bumpIncidentGen').length - 1, 2)
})
