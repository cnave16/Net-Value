import PlayerHeadshot from './PlayerHeadshot.jsx'
import { formatMoney, formatSurplus } from '../services/format.js'

export default function PlayerCard({ player, selected, onSelect }) {
  const { name, team, salary, surplus } = player
  const twoWay = player.contract_type === 'two_way'
  // Missed last season or barely played, so the model has nothing to value.
  const noStats = !twoWay && player.value_missing_reason === 'no_recent_stats'
  const tone = surplus == null ? 'neutral' : surplus >= 0 ? 'positive' : 'negative'
  return (
    <button
      type="button"
      className={`player-card ${tone}${selected ? ' selected' : ''}`}
      onClick={() => onSelect(player)}
      aria-pressed={selected}
    >
      <span className="player-team">
        {team ?? '—'}
        {player.at_value_ceiling && (
          <span className="max-tag" title="Fair value is capped at the model's ceiling (the max salary)">Max value</span>
        )}
      </span>
      <span className="player-name">{name}</span>
      <span className="player-stats">
        <span>
          <small>Salary</small>
          {twoWay ? 'Two-way' : formatMoney(salary, 'N/A')}
        </span>
        <span className={`player-surplus ${tone}`}>
          <small>Net</small>
          {twoWay ? '—' : noStats ? <span title="No stats from last season to value">No stats</span> : formatSurplus(surplus, 'N/A')}
        </span>
      </span>
      <PlayerHeadshot player={player} className="card-headshot" />
    </button>
  )
}
