import { useEffect, useState } from 'react'
import { getPlayer, getValuation } from '../services/api.js'
import PlayerHeadshot from './PlayerHeadshot.jsx'
import { formatMoney, formatRating, formatSeason, formatSurplus } from '../services/format.js'

// Selected-player detail: fair value vs. actual salary, and the surplus/deficit.
export default function PlayerDetailPanel({ playerId }) {
  const [state, setState] = useState({ status: 'idle' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (playerId == null) return
    let cancelled = false
    setState({ status: 'loading' })
    Promise.all([getPlayer(playerId), getValuation(playerId)])
      .then(([player, valuation]) => {
        if (cancelled) return
        setState({
          status: 'ready',
          player: player.data,
          valuation: valuation.data,
          isMock: Boolean(player.isMock || valuation.isMock),
          notImplemented: Boolean(valuation.notImplemented),
        })
      })
      .catch((error) => !cancelled && setState({ status: 'error', error }))
    return () => { cancelled = true }
  }, [playerId, retry])

  if (playerId == null) {
    return <aside className="detail-panel empty">Select a player to see their value.</aside>
  }
  if (state.status === 'loading' || state.status === 'idle') {
    return <aside className="detail-panel empty">Loading…</aside>
  }
  if (state.status === 'error') {
    return (
      <aside className="detail-panel empty">
        <p>{state.error.message}</p>
        <button type="button" onClick={() => setRetry((n) => n + 1)}>Retry</button>
      </aside>
    )
  }

  const { player, valuation, isMock, notImplemented } = state
  const salary = valuation.salary ?? player.salary
  const fairValue = valuation.predicted_value ?? player.predicted_value
  const surplus = valuation.surplus ?? (salary != null && fairValue != null ? fairValue - salary : null)
  const max = Math.max(salary ?? 0, fairValue ?? 0) || 1
  const tone = surplus == null ? '' : surplus >= 0 ? 'positive' : 'negative'
  // Newest season first. Its teams are historical, so label them with the season.
  const latest = player.seasons?.[0]
  const teamLabel = player.team
    ?? (latest?.teams?.length ? `${latest.teams.join(' / ')} · ${formatSeason(latest)}` : 'Team unavailable')

  return (
    <aside className="detail-panel">
      <header className="detail-header">
        <PlayerHeadshot player={player} className="detail-headshot" />
        <span className="eyebrow">Scouting report{isMock ? ' · Sample data' : ''}</span>
        <h2>{player.name}</h2>
        <span className="detail-team">{teamLabel}</span>
      </header>

      <div className="detail-body">
        {latest && <SeasonStats season={latest} />}

        <div className="stat-grid">
          <div className="stat">
            <small>Fair value</small>
            <strong>{formatMoney(fairValue)}</strong>
          </div>
          <div className="stat">
            <small>Salary</small>
            <strong>{formatMoney(salary)}</strong>
          </div>
        </div>

        <div className="value-bars">
          <ValueBar label="Value" value={fairValue} max={max} className="fair" />
          <ValueBar label="Salary" value={salary} max={max} className="salary" />
        </div>

        <div className={`surplus ${tone || 'neutral'}`}>
          <span>{surplus == null ? 'Net value' : surplus >= 0 ? 'Surplus' : 'Deficit'}</span>
          <strong>{formatSurplus(surplus)}</strong>
        </div>
        {surplus != null && (
          <p className="muted">
            {surplus >= 0
              ? 'Produces more value than the contract pays.'
              : 'Paid more than the value produced.'}
          </p>
        )}
        {isMock && <p className="muted fine">Sample data: not real valuations.</p>}
        {notImplemented && (
          <p className="muted">The valuation model isn't connected to the backend yet.</p>
        )}
      </div>
    </aside>
  )
}

function SeasonStats({ season }) {
  const { games_played: games, minutes_played: minutes } = season
  const mpg = games && minutes != null ? (minutes / games).toFixed(1) : '—'
  const ratingTone = (value) => (value == null ? '' : value >= 0 ? 'positive' : 'negative')
  return (
    <section className="season-stats">
      <small className="section-label">{formatSeason(season)} season</small>
      <div className="season-grid">
        <div><small>GP</small><strong>{games ?? '—'}</strong></div>
        <div><small>MPG</small><strong>{mpg}</strong></div>
        <div><small>LEBRON</small><strong className={ratingTone(season.lebron)}>{formatRating(season.lebron)}</strong></div>
        <div><small>O-LEB</small><strong className={ratingTone(season.offensive_lebron)}>{formatRating(season.offensive_lebron)}</strong></div>
        <div><small>D-LEB</small><strong className={ratingTone(season.defensive_lebron)}>{formatRating(season.defensive_lebron)}</strong></div>
      </div>
    </section>
  )
}

function ValueBar({ label, value, max, className }) {
  const width = value == null ? 0 : Math.max(2, (value / max) * 100)
  return (
    <div className="value-bar">
      <span className="value-bar-label">{label}</span>
      <div className="value-bar-track">
        <div className={`value-bar-fill ${className}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}
