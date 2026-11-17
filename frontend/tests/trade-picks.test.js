// Exercise pick routing, URL restoration, and the payload actually sent to the API.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/pages/TradePage.jsx', import.meta.url), 'utf8')
const parse = source.match(/function parseTradeParams\([^]*?\n}/)[0]
const handlers = ['changed', 'retarget', 'togglePlayer', 'setDestination', 'defaultDestination', 'reset', 'analyze']
  .map((name) => source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`))[0]).join('\n')

function setup() {
  const context = vm.createContext({
    MAX_TEAMS: 5, URLSearchParams,
    positiveInt: (s) => /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null,
    newSlot: (teamId = null) => ({ teamId }),
    moves: {}, teamIds: [1, 2, 3], season: { id: 1 }, moveList: [], pickMoveList: [],
    analysisVersion: { current: 0 }, idle: { status: 'idle' },
    setSlots: () => {},
  })
  context.setMoves = (value) => { context.moves = value }
  context.setResult = (value) => { context.result = value }
  context.analyzeTrade = (value) => { context.payload = value; return new Promise(() => {}) }
  vm.runInContext(`${parse}\n${handlers}`, context)
  return { context, run: (code) => vm.runInContext(code, context) }
}

test('shared links restore players and distinct picks, rejecting invalid pick routes', () => {
  const { run } = setup()
  const result = run(`parseTradeParams(new URLSearchParams('t=1,2&m=9-1-2&p=2027-1-3-1-2,2027-2-3-1-2,2028-3-1-1-2,2029-1-1-1-1'), new Set([1,2,3]))`)
  assert.deepEqual(Object.keys(result.moves).sort(), ['9', 'pick:2027-1-3', 'pick:2027-2-3'])
  assert.equal(result.moves['pick:2027-1-3'].from, 1)
})

test('pick selection, destination changes and reset invalidate pending analysis', () => {
  const { context, run } = setup()
  run(`analyze(); togglePlayer(1, 'pick:2027-2-1')`)
  assert.equal(context.result.status, 'idle')
  assert.equal(context.moves['pick:2027-2-1'].to, 2)
  run(`setDestination('pick:2027-2-1', 3)`)
  assert.equal(context.moves['pick:2027-2-1'].to, 3)
  run(`togglePlayer(1, 'pick:2027-2-1')`)
  assert.equal(Object.keys(context.moves).length, 0)
  run(`togglePlayer(1, 'pick:2028-1-1'); reset()`)
  assert.equal(Object.keys(context.moves).length, 0)
})

test('team replacement and removal retarget both kinds of assets', () => {
  const { run } = setup()
  const remaining = run(`retarget({'pick:2027-1-1': {from:1,to:2}, 'pick:2028-2-2': {from:2,to:1}, 7: {from:3,to:1}}, 1, 4)`)
  assert.equal(remaining['pick:2027-1-1'], undefined)
  assert.equal(remaining['pick:2028-2-2'].to, 4)
  assert.equal(remaining['7'].to, 4)
  assert.equal(run(`Object.keys(retarget({'pick:2028-2-2': {from:2,to:1}}, 1, null)).length`), 0)
})

test('pick-only analysis keeps player transfers empty and sends pick transfers', () => {
  const { context, run } = setup()
  context.pickMoveList = [{ draft_year: 2027, round: 2, original_team_id: 1, from_team_id: 1, to_team_id: 2 }]
  run('analyze()')
  assert.equal(context.payload.transfers.length, 0)
  assert.equal(context.payload.pickTransfers[0].draft_year, 2027)
})

test('API adapter sends separate player and pick arrays', () => {
  const api = readFileSync(new URL('../src/services/api.js', import.meta.url), 'utf8')
  const fn = api.match(/export function analyzeTrade\([^]*?\n}/)[0].replace('export ', '')
  const context = vm.createContext({ request: (value) => value })
  vm.runInContext(fn, context)
  const result = vm.runInContext(`analyzeTrade({seasonId:1,teamIds:[1,2],transfers:[],pickTransfers:[{draft_year:2027,round:2,original_team_id:1,from_team_id:1,to_team_id:2}]})`, context)
  assert.equal(result.data.pick_transfers[0].original_team_id, 1)
  assert.equal(result.data.transfers.length, 0)
})
