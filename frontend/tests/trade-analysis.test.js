// Exercise the page's actual handlers with delayed responses and controlled state.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/pages/TradePage.jsx', import.meta.url), 'utf8')
const handlers = ['changed', 'reset', 'addTeam', 'analyze'].map((name) => {
  const match = source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`))
  assert.ok(match, `Missing page handler: ${name}`)
  return match[0]
}).join('\n')

function page() {
  const pending = []
  let result
  const context = vm.createContext({
    idle: { status: 'idle' }, analysisVersion: { current: 0 },
    season: { id: 1 }, teamIds: [1, 2], moveList: [], pickMoveList: [], moves: {}, slots: [{}, {}],
    setResult: (value) => { result = value }, setMoves: () => {}, setSlots: () => {}, newSlot: () => ({}),
    analyzeTrade: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  })
  vm.runInContext(handlers, context)
  return { context, pending, result: () => result, run: (code) => vm.runInContext(code, context) }
}

const flush = () => new Promise((resolve) => setImmediate(resolve))

for (const edit of ['changed({})', 'reset()', 'addTeam()']) {
  for (const outcome of ['resolve', 'reject']) {
    test(`${edit} ignores a pending ${outcome}`, async () => {
      const p = page()
      p.run(`analyze(); ${edit}`)
      assert.equal(p.result().status, 'idle')
      p.pending[0][outcome](outcome === 'resolve' ? { data: { old: true }, meta: {} } : new Error('old failure'))
      await flush()
      assert.equal(p.result().status, 'idle')
    })
  }
}

test('only the newest request can publish results', async () => {
  const p = page()
  p.run('analyze(); changed({}); analyze()')
  p.pending[1].resolve({ data: { current: true }, meta: {} })
  await flush()
  p.pending[0].resolve({ data: { old: true }, meta: {} })
  await flush()
  assert.equal(p.result().data.current, true)
})

test('an unchanged request still displays success or failure', async () => {
  const p = page()
  p.run('analyze()')
  p.pending[0].resolve({ data: { valid: true }, meta: {} })
  await flush()
  assert.equal(p.result().data.valid, true)
  p.run('analyze()')
  p.pending[1].reject(new Error('current failure'))
  await flush()
  assert.equal(p.result().status, 'error')
  assert.equal(p.result().error.message, 'current failure')
})
