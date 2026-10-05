// Sample data for building the UI before the backend supplies salaries and
// valuations. Shapes match docs/api.md. Salaries are approximate 2025-26
// figures and fair values are made up: always label this data as an example.

const PLAYERS = [
  { id: 1, name: 'Stephen Curry', team: 'GSW', salary: 59_606_817, predicted_value: 48_500_000 },
  { id: 2, name: 'Nikola Jokic', team: 'DEN', salary: 55_224_526, predicted_value: 71_000_000 },
  { id: 3, name: 'Shai Gilgeous-Alexander', team: 'OKC', salary: 38_333_050, predicted_value: 66_000_000 },
  { id: 4, name: 'Giannis Antetokounmpo', team: 'MIL', salary: 54_126_450, predicted_value: 62_500_000 },
  { id: 5, name: 'Jalen Brunson', team: 'NYK', salary: 34_944_001, predicted_value: 44_000_000 },
  { id: 6, name: 'Victor Wembanyama', team: 'SAS', salary: 13_376_880, predicted_value: 52_000_000 },
  { id: 7, name: 'Bradley Beal', team: 'LAC', salary: 5_200_000, predicted_value: 9_000_000 },
  { id: 8, name: 'Jayson Tatum', team: 'BOS', salary: 54_126_450, predicted_value: null },
  { id: 9, name: 'Zach LaVine', team: 'SAC', salary: 47_499_660, predicted_value: 27_000_000 },
  { id: 10, name: 'Tyrese Haliburton', team: 'IND', salary: 45_550_512, predicted_value: null },
  { id: 11, name: 'Anthony Edwards', team: 'MIN', salary: 45_550_512, predicted_value: 53_000_000 },
  { id: 12, name: 'Cade Cunningham', team: 'DET', salary: 46_394_100, predicted_value: 47_500_000 },
  { id: 13, name: 'Chet Holmgren', team: 'OKC', salary: 13_731_368, predicted_value: 31_000_000 },
  { id: 14, name: 'Paul George', team: 'PHI', salary: 51_666_090, predicted_value: 24_000_000 },
  { id: 15, name: 'Amen Thompson', team: 'HOU', salary: 9_635_640, predicted_value: 28_500_000 },
]

const delay = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))

function toPlayer(p) {
  return {
    id: p.id,
    name: p.name,
    external_id: null,
    team: p.team,
    salary: p.salary,
    predicted_value: p.predicted_value,
    surplus: p.predicted_value == null ? null : p.predicted_value - p.salary,
  }
}

function notFound() {
  return Object.assign(new Error('Player not found.'), { status: 404, code: 'NOT_FOUND' })
}

export async function getPlayers({ search = '', page = 1, limit = 20 }) {
  await delay()
  const term = search.trim().toLowerCase()
  const matches = PLAYERS.filter((p) => p.name.toLowerCase().includes(term))
  const start = (page - 1) * limit
  return {
    data: matches.slice(start, start + limit).map(toPlayer),
    meta: {
      page, limit, total: matches.length,
      total_pages: Math.ceil(matches.length / limit),
      season_id: null, team_filter: null,
    },
    isMock: true,
  }
}

export async function getPlayer(id) {
  await delay()
  const player = PLAYERS.find((p) => p.id === Number(id))
  if (!player) throw notFound()
  return { data: toPlayer(player), meta: {}, isMock: true }
}

export async function getValuation(playerId) {
  await delay()
  const player = PLAYERS.find((p) => p.id === Number(playerId))
  const { salary = null, predicted_value = null, surplus = null } = player ? toPlayer(player) : {}
  return {
    data: { player_id: Number(playerId), salary, predicted_value, surplus },
    meta: {},
    isMock: true,
  }
}
