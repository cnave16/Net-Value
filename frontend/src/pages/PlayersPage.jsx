import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import PlayerCard from '../components/PlayerCard.jsx'
import PlayerDetailPanel from '../components/PlayerDetailPanel.jsx'
import SearchBar from '../components/SearchBar.jsx'
import useDebounce from '../hooks/useDebounce.js'
import { getPlayers } from '../services/api.js'

const PAGE_SIZE = 30
const SORTS = [
  { value: 'name', label: 'Name (A–Z)' },
  { value: 'best_value', label: 'Most underpaid' },
  { value: 'worst_value', label: 'Most overpaid' },
  { value: 'salary', label: 'Highest salary' },
]

export default function PlayersPage() {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('name')
  const debouncedSearch = useDebounce(search, 300)
  // players accumulate across "Load more"; a new search or sort starts over.
  const [state, setState] = useState({ status: 'loading', players: [], page: 1, total: 0, meta: {} })
  // Keep the selection in the URL (?player=3) so it survives reloads and can be shared.
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('player') ? Number(params.get('player')) : null
  const setSelectedId = (id) => setParams({ player: String(id) }, { replace: true })

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, status: 'loading' }))
    getPlayers({ search: debouncedSearch, sort, limit: PAGE_SIZE })
      .then(({ data, meta }) => !cancelled && setState({
        status: 'ready', players: data, page: 1, total: meta.total ?? data.length, meta,
      }))
      .catch((error) => !cancelled && setState({ status: 'error', players: [], page: 1, total: 0, meta: {}, error }))
    return () => { cancelled = true }
  }, [debouncedSearch, sort])

  function loadMore() {
    const next = state.page + 1
    setState((s) => ({ ...s, status: 'loading-more' }))
    getPlayers({ search: debouncedSearch, sort, limit: PAGE_SIZE, page: next })
      .then(({ data }) => setState((s) => ({ ...s, status: 'ready', page: next, players: [...s.players, ...data] })))
      .catch((error) => setState((s) => ({ ...s, status: 'error', error })))
  }

  const more = state.players.length < state.total

  return (
    <section className="page players-page">
      <div className="player-list">
        <h1>Players</h1>
        <SearchBar value={search} onChange={setSearch} />
        <div className="list-controls">
          <label>
            <small>Sort by</small>
            <select className="trade-select" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          {state.total > 0 && (
            <span className="muted">Showing {state.players.length} of {state.total} players on 2026–27 rosters</span>
          )}
        </div>
        {state.meta?.min_ranked_games && (
          <p className="fine muted list-note">
            Ranked among players with {state.meta.min_ranked_games}+ games last season, since fair value grows with
            minutes; injury-shortened seasons and players without a value follow.
          </p>
        )}
        {state.status === 'error' && <p className="error">{state.error.message}</p>}
        {state.status === 'ready' && state.players.length === 0 && (
          <p className="muted">No players found.</p>
        )}
        <div className={`cards${state.status === 'loading' ? ' loading' : ''}`}>
          {state.players.map((player) => (
            <PlayerCard
              key={player.id}
              player={player}
              selected={player.id === selectedId}
              onSelect={(p) => setSelectedId(p.id)}
            />
          ))}
        </div>
        {more && (
          <button type="button" className="trade-secondary load-more" onClick={loadMore}
            disabled={state.status === 'loading-more' || state.status === 'loading'}>
            {state.status === 'loading-more' ? 'Loading…' : `Load ${Math.min(PAGE_SIZE, state.total - state.players.length)} more`}
          </button>
        )}
      </div>
      <PlayerDetailPanel playerId={selectedId} />
    </section>
  )
}
