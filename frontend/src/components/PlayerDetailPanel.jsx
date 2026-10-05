import { useEffect, useState } from 'react'
import { getPlayer, getValuation } from '../services/api.js'
import { formatMoney, formatSurplus } from '../services/format.js'

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

  return (
    <aside className="detail-panel">
      {isMock && <p className="badge">Sample data: not real valuations</p>}
      <h2>{player.name}</h2>
      <p className="muted">{player.team ?? 'Team unavailable'}</p>

      <div className="value-bars">
        <ValueBar label="Fair value" value={fairValue} max={max} className="fair" />
        <ValueBar label="Actual salary" value={salary} max={max} className="salary" />
      </div>

      <div className={`surplus ${tone}`}>
        <span>{surplus == null ? 'Surplus / deficit' : surplus >= 0 ? 'Surplus' : 'Deficit'}</span>
        <strong>{formatSurplus(surplus)}</strong>
      </div>
      {surplus != null && (
        <p className="muted">
          {surplus >= 0
            ? 'Produces more value than the contract pays.'
            : 'Paid more than the value produced.'}
        </p>
      )}
      {notImplemented && (
        <p className="muted">The valuation model isn't connected to the backend yet.</p>
      )}
    </aside>
  )
}

function ValueBar({ label, value, max, className }) {
  const width = value == null ? 0 : Math.max(2, (value / max) * 100)
  return (
    <div className="value-bar">
      <div className="value-bar-label">
        <span>{label}</span>
        <span>{formatMoney(value)}</span>
      </div>
      <div className="value-bar-track">
        <div className={`value-bar-fill ${className}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}
