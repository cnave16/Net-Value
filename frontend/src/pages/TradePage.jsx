import { useEffect, useRef, useState } from 'react'
import { analyzeTrade, getSeasons, getTeams, getTradeTeam, USE_MOCK } from '../services/api.js'
import { formatMoney, formatSeason } from '../services/format.js'

// Two-team trade builder. The backend accepts 2–30 teams; two covers the common case.
// Checked players move to the other team; analysis runs on the selected season's data.

function signed(value, digits = 1) {
  if (value == null) return '—'
  const rounded = Number(value.toFixed(digits))
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded).toFixed(digits)}`
}

function tone(value) {
  if (value == null || Math.abs(value) < 0.05) return ''
  return value > 0 ? 'positive' : 'negative'
}

// Money arrives as decimal strings; null means unavailable, never zero.
const dollars = (value) => (value == null ? null : Number(value))

function TeamColumn({ label, teams, teamId, otherTeamId, onTeamChange, roster, selected, onToggle }) {
  const players = roster.status === 'ready'
    ? [...roster.team.roster].sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0))
    : []
  return (
    <div className="trade-team">
      <small className="section-label">{label}</small>
      <select
        className="trade-select"
        value={teamId ?? ''}
        onChange={(e) => onTeamChange(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">Select a team</option>
        {teams.map((team) => (
          <option key={team.id} value={team.id} disabled={team.id === otherTeamId}>
            {team.abbreviation} · {team.name}
          </option>
        ))}
      </select>
      {roster.status === 'loading' && <p className="muted">Loading roster…</p>}
      {roster.status === 'error' && <p className="error">{roster.error.message}</p>}
      {roster.status === 'ready' && (
        <>
          <div className="trade-team-summary">
            <div><small>Projected wins</small><strong>{roster.team.projected_wins.toFixed(1)}</strong></div>
            <div><small>Payroll</small><strong>{formatMoney(dollars(roster.team.payroll.before), 'Incomplete')}</strong></div>
          </div>
          <ul className="trade-roster">
            {players.map((player) => (
              <li key={player.player_id}>
                <label className={selected.has(player.player_id) ? 'checked' : ''}>
                  <input
                    type="checkbox"
                    checked={selected.has(player.player_id)}
                    onChange={() => onToggle(player.player_id)}
                  />
                  <span className="trade-player-name">{player.name}</span>
                  <span className="trade-player-meta">{Math.round(player.minutes ?? 0)} min</span>
                  <span className="trade-player-meta">{formatMoney(dollars(player.actual_salary), 'No salary')}</span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function TeamResult({ team, names }) {
  const wins = team.projected_wins
  const payroll = team.payroll
  const cap = team.salary_cap
  const list = (ids) => ids.map((id) => names[id] ?? `#${id}`).join(', ') || 'Nothing'
  return (
    <div className="trade-result-team">
      <h2>{team.abbreviation}</h2>
      <p className="fine muted">Gets: {list(team.incoming_player_ids)}<br />Sends: {list(team.outgoing_player_ids)}</p>
      <div className={`surplus ${tone(wins.net_difference)}`}>
        <span>Projected wins</span>
        <strong>{signed(wins.net_difference)}</strong>
      </div>
      <div className="stat-grid trade-stats">
        <div className="stat"><small>Wins before</small><strong>{wins.before.toFixed(1)}</strong></div>
        <div className="stat"><small>Wins after</small><strong>{wins.after.toFixed(1)}</strong></div>
        <div className="stat"><small>Payroll after</small><strong>{formatMoney(dollars(payroll.after), '—')}</strong></div>
        <div className="stat"><small>Cap space after</small><strong>{formatMoney(dollars(cap.after), '—')}</strong></div>
      </div>
      {(payroll.after == null) && (
        <p className="fine muted">Payroll is incomplete: some players have no salary on file.</p>
      )}
    </div>
  )
}

function Legality({ legality, abbreviations }) {
  const verdict = legality.status === 'failed'
    ? { tone: 'negative', text: 'Fails CBA rules' }
    : legality.passes_supported_rules
      ? { tone: 'positive', text: 'Passes supported CBA rules' }
      : { tone: '', text: 'Needs review' }
  return (
    <div className="trade-legality">
      <div className={`surplus ${verdict.tone}`}><span>{verdict.text}</span></div>
      <ul className="trade-checks">
        {legality.checks.map((check, i) => (
          <li key={i} className={check.passed === true ? 'positive' : check.passed === false ? 'negative' : ''}>
            <strong>{check.passed === true ? '✓' : check.passed === false ? '✗' : '?'}</strong>
            <span>
              {check.team_id && <b>{abbreviations[check.team_id]} </b>}
              {check.message}
              {check.incoming_salary != null && check.maximum_incoming_salary != null && (
                <span className="muted"> Incoming {formatMoney(dollars(check.incoming_salary))}, max {formatMoney(dollars(check.maximum_incoming_salary))}.</span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {legality.not_checked?.length > 0 && (
        <p className="fine muted">
          Not checked yet: {legality.not_checked.map((rule) => rule.replaceAll('_', ' ')).join('; ')}.
        </p>
      )}
    </div>
  )
}

const idle = { status: 'idle' }

export default function TradePage() {
  const [teams, setTeams] = useState([])
  const [season, setSeason] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [teamIds, setTeamIds] = useState([null, null])
  const [rosters, setRosters] = useState([idle, idle])
  const [selected, setSelected] = useState([new Set(), new Set()])
  const [result, setResult] = useState(idle)
  // Latest team per side, so a slow roster response for a replaced team is ignored.
  const latestTeamIds = useRef([null, null])

  useEffect(() => {
    if (USE_MOCK) return
    Promise.all([getTeams(), getSeasons()])
      .then(([teamsRes, seasonsRes]) => {
        setTeams(teamsRes.data)
        setSeason(seasonsRes.data[0] ?? null) // newest first
      })
      .catch(setLoadError)
  }, [])

  function chooseTeam(side, teamId) {
    latestTeamIds.current[side] = teamId
    setTeamIds((ids) => ids.map((id, i) => (i === side ? teamId : id)))
    setSelected((sets) => sets.map((set, i) => (i === side ? new Set() : set)))
    setResult(idle)
    if (!teamId) {
      setRosters((rs) => rs.map((r, i) => (i === side ? idle : r)))
      return
    }
    setRosters((rs) => rs.map((r, i) => (i === side ? { status: 'loading' } : r)))
    getTradeTeam(teamId, season.id)
      .then(({ data }) => ({ status: 'ready', team: data }))
      .catch((error) => ({ status: 'error', error }))
      .then((roster) => {
        if (latestTeamIds.current[side] !== teamId) return
        setRosters((rs) => rs.map((r, i) => (i === side ? roster : r)))
      })
  }

  function togglePlayer(side, playerId) {
    setSelected((sets) => sets.map((set, i) => {
      if (i !== side) return set
      const next = new Set(set)
      if (next.has(playerId)) next.delete(playerId)
      else next.add(playerId)
      return next
    }))
    setResult(idle)
  }

  const [teamA, teamB] = teamIds
  const ready = rosters.every((r) => r.status === 'ready')
  const moving = selected[0].size + selected[1].size
  // The roster data is last season's, so a player traded mid-season is listed on both
  // teams. The backend rejects any trade between two such teams, so catch it up front.
  const shared = ready
    ? rosters[0].team.roster.filter((a) => rosters[1].team.roster.some((b) => b.player_id === a.player_id))
    : []
  const canAnalyze = ready && moving > 0 && shared.length === 0 && result.status !== 'loading'

  function analyze() {
    const transfers = [
      ...[...selected[0]].map((id) => ({ player_id: id, from_team_id: teamA, to_team_id: teamB })),
      ...[...selected[1]].map((id) => ({ player_id: id, from_team_id: teamB, to_team_id: teamA })),
    ]
    setResult({ status: 'loading' })
    analyzeTrade({ seasonId: season.id, teamIds: [teamA, teamB], transfers })
      .then(({ data }) => setResult({ status: 'ready', data }))
      .catch((error) => setResult({ status: 'error', error }))
  }

  if (USE_MOCK) {
    return (
      <section className="page">
        <h1>Trade Simulator</h1>
        <p className="muted">The trade simulator needs the live backend. Set VITE_USE_MOCK=false in frontend/.env.local and restart Vite.</p>
      </section>
    )
  }

  const names = {}
  const abbreviations = {}
  rosters.forEach((r) => {
    if (r.status !== 'ready') return
    abbreviations[r.team.team_id] = r.team.abbreviation
    r.team.roster.forEach((p) => { names[p.player_id] = p.name })
  })

  return (
    <section className="page trade-page">
      <h1>Trade Simulator</h1>
      <p className="muted">
        Pick two teams and check the players each one sends. Projections use{' '}
        {season ? formatSeason(season) : '…'} ratings and minutes; salary rules use the 2026–27 cap.
      </p>
      {loadError && <p className="error">{loadError.message}</p>}

      <div className="trade-builder">
        {[0, 1].map((side) => (
          <TeamColumn
            key={side}
            label={side === 0 ? 'Team A sends' : 'Team B sends'}
            teams={teams}
            teamId={teamIds[side]}
            otherTeamId={teamIds[1 - side]}
            onTeamChange={(id) => chooseTeam(side, id)}
            roster={rosters[side]}
            selected={selected[side]}
            onToggle={(id) => togglePlayer(side, id)}
          />
        ))}
      </div>

      <div className="trade-actions">
        <button type="button" className="trade-button" disabled={!canAnalyze} onClick={analyze}>
          {result.status === 'loading' ? 'Analyzing…' : 'Analyze trade'}
        </button>
        {ready && shared.length === 0 && moving === 0 && <span className="muted">Check at least one player to trade.</span>}
      </div>

      {shared.length > 0 && (
        <p className="error">
          {shared.map((p) => p.name).join(', ')} played for both {rosters[0].team.abbreviation} and{' '}
          {rosters[1].team.abbreviation} last season, so the simulator can't split these rosters yet.
          Pick a different team.
        </p>
      )}
      {result.status === 'error' && <p className="error">{result.error.message}</p>}
      {result.status === 'ready' && (
        <div className="trade-results">
          {!result.data.analysis_available && (
            <p className="error">Win projections are unavailable for this trade.</p>
          )}
          <div className="trade-builder">
            {result.data.teams.map((team) => <TeamResult key={team.team_id} team={team} names={names} />)}
          </div>
          <Legality legality={result.data.legality} abbreviations={abbreviations} />
        </div>
      )}
    </section>
  )
}
