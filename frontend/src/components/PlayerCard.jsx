import { formatMoney, formatSurplus } from '../services/format.js'

export default function PlayerCard({ player, selected, onSelect }) {
  const { name, team, salary, surplus } = player
  const tone = surplus == null ? '' : surplus >= 0 ? 'positive' : 'negative'
  return (
    <button
      type="button"
      className={`player-card${selected ? ' selected' : ''}`}
      onClick={() => onSelect(player)}
      aria-pressed={selected}
    >
      <span className="player-name">{name}</span>
      <span className="player-meta">{team ?? 'Team unavailable'} · {formatMoney(salary)}</span>
      <span className={`player-surplus ${tone}`}>{formatSurplus(surplus)}</span>
    </button>
  )
}
