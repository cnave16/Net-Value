import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import PlayerCard from '../components/PlayerCard.jsx'
import PlayerDetailPanel from '../components/PlayerDetailPanel.jsx'
import SearchBar from '../components/SearchBar.jsx'
import useDebounce from '../hooks/useDebounce.js'
import { getPlayers } from '../services/api.js'

export default function PlayersPage() {
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounce(search, 300)
  const [state, setState] = useState({ status: 'loading', players: [] })
  // Keep the selection in the URL (?player=3) so it survives reloads and can be shared.
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('player') ? Number(params.get('player')) : null
  const setSelectedId = (id) => setParams({ player: String(id) }, { replace: true })

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, status: 'loading' }))
    getPlayers({ search: debouncedSearch })
      .then(({ data }) => !cancelled && setState({ status: 'ready', players: data }))
      .catch((error) => !cancelled && setState({ status: 'error', players: [], error }))
    return () => { cancelled = true }
  }, [debouncedSearch])

  return (
    <section className="page players-page">
      <div className="player-list">
        <h1>Players</h1>
        <SearchBar value={search} onChange={setSearch} />
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
      </div>
      <PlayerDetailPanel playerId={selectedId} />
    </section>
  )
}
