import PlayerHeadshot from './PlayerHeadshot.jsx'
import { formatMoney, formatSurplus } from '../services/format.js'

export default function PlayerCard({ player, selected, onSelect }) {
  const { name, team, salary, surplus } = player
  const tone = surplus == null ? 'neutral' : surplus >= 0 ? 'positive' : 'negative'
  return (
    <button
      type="button"
      className={`player-card ${tone}${selected ? ' selected' : ''}`}
      onClick={() => onSelect(player)}
      aria-pressed={selected}
    >
      <span className="player-team">{team ?? '—'}</span>
      <span className="player-name">{name}</span>
      <span className="player-stats">
        <span>
          <small>Salary</small>
          {formatMoney(salary, 'N/A')}
        </span>
        <span className={`player-surplus ${tone}`}>
          <small>Net</small>
          {formatSurplus(surplus, 'N/A')}
        </span>
      </span>
      <PlayerHeadshot player={player} className="card-headshot" />
    </button>
  )
}
