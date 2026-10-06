import { useState } from 'react'

// external_id is the NBA person ID (imported from the CSV's nba_id column).
const headshotUrl = (nbaId) => `https://cdn.nba.com/headshots/nba/latest/1040x760/${nbaId}.png`

function initials(name = '') {
  return name.split(' ').map((part) => part[0]).slice(0, 2).join('')
}

export default function PlayerHeadshot({ player, className = '' }) {
  const [failedId, setFailedId] = useState(null)
  const id = player.external_id
  if (!id || failedId === id) {
    return <span className={`headshot headshot-fallback ${className}`}>{initials(player.name)}</span>
  }
  return (
    <img
      className={`headshot ${className}`}
      src={headshotUrl(id)}
      alt=""
      loading="lazy"
      onError={() => setFailedId(id)}
    />
  )
}
