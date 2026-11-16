// Exercise the actual budget handlers with delayed API replies.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/pages/TradePage.jsx', import.meta.url), 'utf8')
const handlers = ['applyBudget', 'clearBudget'].map((name) => source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`))[0]).join('\n')
const flush = () => new Promise((resolve) => setImmediate(resolve))
function page(budget = '10000000') {
  let state
  const pending = []
  const context = vm.createContext({ budget, slot: { teamId: 20 }, seasonId: 1, targetVersion: { current: 0 },
    setFiltered: (value) => { state = value }, setShowAllTargets: () => {},
    setBudget: (value) => { context.budget = value },
    getTradeTeam: (...args) => new Promise((resolve, reject) => pending.push({ args, resolve, reject })),
  })
  vm.runInContext(handlers, context)
  return { context, pending, state: () => state, apply: () => vm.runInContext('applyBudget({ preventDefault() {} })', context),
    clear: () => vm.runInContext('clearBudget()', context) }
}

test('budget request keeps exact dollars and cents', async () => {
  const p = page('2000000.19')
  p.apply()
  assert.deepEqual(p.pending[0].args, [20, 1, '2000000.19'])
  p.pending[0].resolve({ data: { targets: [], available_salary: '2000000.19' } })
  await flush()
  assert.equal(p.state().status, 'ready')
})
for (const outcome of ['resolve', 'reject']) {
  test(`clear ignores a pending ${outcome}`, async () => {
    const p = page()
    p.apply()
    p.clear()
    p.pending[0][outcome](outcome === 'resolve' ? { data: {} } : new Error('old'))
    await flush()
    assert.equal(p.state(), null)
    assert.equal(p.context.budget, '')
  })
}
test('newest applied budget wins', async () => {
  const p = page()
  p.apply()
  p.context.budget = '5000000'
  p.apply()
  p.pending[1].resolve({ data: { available_salary: '5000000.00' } })
  await flush()
  p.pending[0].resolve({ data: { available_salary: '10000000.00' } })
  await flush()
  assert.equal(p.state().team.available_salary, '5000000.00')
})
test('blank resets while zero requests an explicit zero budget', () => {
  const p = page(' ')
  p.apply()
  assert.equal(p.state(), null)
  assert.equal(p.pending.length, 0)
  p.context.budget = '0'
  p.apply()
  assert.equal(p.pending[0].args[2], '0')
})
test('invalid budget and request errors are displayed', async () => {
  const p = page('-1')
  p.apply()
  assert.equal(p.state().status, 'error')
  assert.equal(p.pending.length, 0)
  p.context.budget = '100'
  p.apply()
  p.pending[0].reject(new Error('Server unavailable'))
  await flush()
  assert.equal(p.state().error, 'Server unavailable')
})
