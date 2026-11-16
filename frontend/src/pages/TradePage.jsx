import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { analyzeTrade, getSeasons, getTeams, getTradeTeam, USE_MOCK } from '../services/api.js'
import { formatMoney, formatSeason } from '../services/format.js'

// Multi-team trade builder. Each checked player moves from their roster to a chosen
// destination; the backend accepts 2–30 teams, the UI caps it at MAX_TEAMS for legibility.
// The trade lives in the URL (?t=teamIds&m=player-from-to,...) so it can be shared.

const MAX_TEAMS = 5
const TARGETS_SHOWN = 5

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

// Sum the salaries on file and list who has none. The backend returns null for an
// incomplete total; the UI shows the known part as a lower bound ("$148M+") instead.
function salarySummary(players) {
  let total = 0
  const missing = []
  for (const p of players) {
    if (p.actual_salary == null) missing.push(p.name)
    else total += Number(p.actual_salary)
  }
  return { total, known: players.length - missing.length, missing }
}

function SalaryAmount({ players }) {
  const { total, known, missing } = salarySummary(players)
  if (missing.length === 0) return <strong>{formatMoney(total)}</strong>
  return (
    <>
      <strong>{known > 0 ? `${formatMoney(total)}+` : 'Unknown'}</strong>
      <span className="salary-missing" title={missing.join(', ')}>
        {missing.length} without salary
      </span>
    </>
  )
}

let slotKey = 0
const newSlot = (teamId = null) => ({ key: slotKey++, teamId })

const positiveInt = (s) => (/^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null)

// Read ?t=1,2&m=101-1-2 into slots and moves, dropping anything inconsistent.
function parseTradeParams(params, knownTeamIds) {
  const teamIds = [...new Set((params.get('t') ?? '').split(',').map(positiveInt))]
    .filter((id) => id && knownTeamIds.has(id))
    .slice(0, MAX_TEAMS)
  const moves = {}
  for (const part of (params.get('m') ?? '').split(',')) {
    const [playerId, from, to] = part.split('-').map(positiveInt)
    if (playerId && teamIds.includes(from) && teamIds.includes(to) && from !== to) {
      moves[playerId] = { from, to }
    }
  }
  const slots = teamIds.map(newSlot)
  while (slots.length < 2) slots.push(newSlot())
  return { slots, moves }
}

function TeamColumn({
  index, slot, teams, takenIds, tradeTeamIds, roster, moves, players, canRemove,
  onTeamChange, onRemove, onToggle, onDestination, onRequestTarget, canRequest,
}) {
  const [showAllTargets, setShowAllTargets] = useState(false)
  const teamId = slot.teamId
  const team = roster?.status === 'ready' ? roster.team : null
  const rosterPlayers = team
    ? [...team.roster].sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0))
    : []
  const outgoing = rosterPlayers.filter((p) => moves[p.player_id]?.from === teamId)
  const incoming = Object.entries(moves)
    .filter(([, m]) => m.to === teamId)
    .map(([id]) => players[id]?.player)
    .filter(Boolean)
  const destinations = tradeTeamIds.filter((id) => id !== teamId)
  const abbreviation = (id) => teams.find((t) => t.id === id)?.abbreviation ?? `#${id}`
  const targets = team?.targets ?? []
  const shownTargets = showAllTargets ? targets : targets.slice(0, TARGETS_SHOWN)

  return (
    <div className="trade-team">
      <div className="trade-team-header">
        <small className="section-label">Team {String.fromCharCode(65 + index)}</small>
        {canRemove && (
          <button type="button" className="link-button" onClick={onRemove}>Remove</button>
        )}
      </div>
      <select
        className="trade-select"
        value={teamId ?? ''}
        onChange={(e) => onTeamChange(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">Select a team</option>
        {teams.map((t) => (
          <option key={t.id} value={t.id} disabled={t.id !== teamId && takenIds.includes(t.id)}>
            {t.abbreviation} · {t.team_name}
          </option>
        ))}
      </select>
      {roster?.status === 'loading' && <p className="muted">Loading roster…</p>}
      {roster?.status === 'error' && <p className="error">{roster.error.message}</p>}
      {team && (
        <>
          <div className="trade-team-summary">
            <div><small>Projected wins</small><strong>{team.projected_wins.toFixed(1)}</strong></div>
            <div><small>Payroll</small><SalaryAmount players={team.roster} /></div>
          </div>

          {(outgoing.length > 0 || incoming.length > 0) && (
            <div className="trade-ledger">
              <div>
                <small>Sends</small>
                {outgoing.length > 0 ? <SalaryAmount players={outgoing} /> : <strong>$0</strong>}
                <span className="fine muted">{outgoing.map((p) => p.name).join(', ') || 'Nothing'}</span>
              </div>
              <div>
                <small>Receives</small>
                {incoming.length > 0 ? <SalaryAmount players={incoming} /> : <strong>$0</strong>}
                <span className="fine muted">{incoming.map((p) => p.name).join(', ') || 'Nothing'}</span>
              </div>
            </div>
          )}

          <ul className="trade-roster">
            {rosterPlayers.map((player) => {
              const move = moves[player.player_id]
              const checked = move?.from === teamId
              return (
                <li key={player.player_id} className={checked ? 'checked' : ''}>
                  <label>
                    <input type="checkbox" checked={checked} onChange={() => onToggle(player.player_id)} />
                    <span className="trade-player-name">{player.name}</span>
                    <span className="trade-player-meta">{Math.round(player.minutes ?? 0)} min</span>
                    <span className="trade-player-meta">{formatMoney(dollars(player.actual_salary), 'No salary')}</span>
                  </label>
                  {checked && destinations.length > 0 && (destinations.length > 1 || move.to == null) && (
                    <div className="trade-destination">
                      <span>To</span>
                      <select
                        value={move.to ?? ''}
                        onChange={(e) => onDestination(player.player_id, e.target.value ? Number(e.target.value) : null)}
                      >
                        {move.to == null && <option value="">Choose…</option>}
                        {destinations.map((id) => <option key={id} value={id}>{abbreviation(id)}</option>)}
                      </select>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>

          {targets.length > 0 && (
            <div className="trade-targets">
              <small className="section-label">Top targets</small>
              <p className="fine muted">Projected win change from adding one player, before sending anyone back.</p>
              <ol>
                {shownTargets.map((target) => {
                  const id = target.player.player_id
                  const owner = target.team_id
                  const alreadyMoving = moves[id]?.to === teamId
                  const reason = owner == null
                    ? 'Played for several teams last season, so the current owner is unclear.'
                    : !canRequest(owner)
                      ? `Trade is limited to ${MAX_TEAMS} teams.`
                      : null
                  return (
                    <li key={id}>
                      <span className="trade-player-name">{target.player.name}</span>
                      <span className="trade-player-meta">{owner == null ? 'Multiple' : abbreviation(owner)}</span>
                      <span className={`trade-target-gain ${tone(target.projected_wins.net_difference)}`}>
                        {signed(target.projected_wins.net_difference)} W
                      </span>
                      <button
                        type="button"
                        className="link-button"
                        disabled={alreadyMoving || reason != null}
                        title={reason ?? undefined}
                        onClick={() => onRequestTarget(target)}
                      >
                        {alreadyMoving ? 'Added' : 'Add'}
                      </button>
                    </li>
                  )
                })}
              </ol>
              {targets.length > TARGETS_SHOWN && (
                <button type="button" className="link-button" onClick={() => setShowAllTargets((v) => !v)}>
                  {showAllTargets ? 'Show fewer' : `Show all ${targets.length}`}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function TeamResult({ team, players }) {
  const wins = team.projected_wins
  const payroll = team.payroll
  const cap = team.salary_cap
  const list = (ids) => ids.map((id) => players[id]?.player.name ?? `#${id}`).join(', ') || 'Nothing'
  // Rebuild the post-trade roster from loaded rosters so a partial payroll can be shown.
  const rosterAfter = team.roster_after.map((id) => players[id]?.player ?? { name: `#${id}`, actual_salary: null })
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
        <div className="stat">
          <small>Payroll after</small>
          {payroll.after != null
            ? <strong>{formatMoney(dollars(payroll.after))}</strong>
            : <SalaryAmount players={rosterAfter} />}
        </div>
        <div className="stat"><small>Cap space after</small><strong>{formatMoney(dollars(cap.after), '—')}</strong></div>
      </div>
      {payroll.after == null && (
        <p className="fine muted">
          Payroll counts only players with a salary on file, so it's a minimum. Cap space and
          salary matching need every salary.
        </p>
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
  const [searchParams, setSearchParams] = useSearchParams()
  const [teams, setTeams] = useState([])
  const [season, setSeason] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [hydrated, setHydrated] = useState(false)
  const [slots, setSlots] = useState(() => [newSlot(), newSlot()])
  const [rosters, setRosters] = useState({}) // teamId -> { status, team | error }
  const [moves, setMoves] = useState({}) // playerId -> { from, to }
  const [result, setResult] = useState(idle)
  const [copied, setCopied] = useState(false)
  // Teams whose roster has been requested; rosters are cached for the session.
  const requested = useRef(new Set())

  useEffect(() => {
    if (USE_MOCK) return
    Promise.all([getTeams(), getSeasons()])
      .then(([teamsRes, seasonsRes]) => {
        setTeams(teamsRes.data)
        setSeason(seasonsRes.data[0] ?? null) // newest first
        const restored = parseTradeParams(searchParams, new Set(teamsRes.data.map((t) => t.id)))
        setSlots(restored.slots)
        setMoves(restored.moves)
        setHydrated(true)
      })
      .catch(setLoadError)
    // Read the URL once on load; afterwards the page writes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!season) return
    for (const { teamId } of slots) {
      if (!teamId || requested.current.has(teamId)) continue
      requested.current.add(teamId)
      setRosters((r) => ({ ...r, [teamId]: { status: 'loading' } }))
      getTradeTeam(teamId, season.id)
        .then(({ data }) => ({ status: 'ready', team: data }))
        .catch((error) => {
          requested.current.delete(teamId) // allow a retry by reselecting the team
          return { status: 'error', error }
        })
        .then((roster) => setRosters((r) => ({ ...r, [teamId]: roster })))
    }
  }, [slots, season])

  const teamIds = slots.map((s) => s.teamId).filter(Boolean)

  // Keep the URL in sync so the current trade can be shared or bookmarked.
  useEffect(() => {
    if (!hydrated) return
    const params = {}
    if (teamIds.length) params.t = teamIds.join(',')
    const encoded = Object.entries(moves)
      .filter(([, m]) => m.to != null)
      .map(([id, m]) => `${id}-${m.from}-${m.to}`)
    if (encoded.length) params.m = encoded.join(',')
    setSearchParams(params, { replace: true })
    // teamIds and the URL setter derive from these; listing them would loop.
  }, [hydrated, slots, moves]) // eslint-disable-line react-hooks/exhaustive-deps

  // Every player on a loaded participating roster, plus anyone listed on two of them.
  const players = {}
  const shared = []
  for (const id of teamIds) {
    const roster = rosters[id]
    if (roster?.status !== 'ready') continue
    for (const player of roster.team.roster) {
      const seen = players[player.player_id]
      if (seen && seen.teamId !== id) shared.push({ player, teams: [seen.teamId, id] })
      else players[player.player_id] = { player, teamId: id }
    }
  }

  const ready = slots.length >= 2 && slots.every((s) => s.teamId && rosters[s.teamId]?.status === 'ready')
  // Only moves whose player is actually on the source roster count (guards stale links).
  const moveList = Object.entries(moves)
    .filter(([id, m]) => players[id]?.teamId === m.from)
    .map(([id, m]) => ({ player_id: Number(id), from_team_id: m.from, to_team_id: m.to }))
  const undirected = moveList.filter((m) => m.to_team_id == null)
  const uninvolved = teamIds.filter((id) => !moveList.some((m) => m.from_team_id === id || m.to_team_id === id))
  const canAnalyze = ready && moveList.length > 0 && undirected.length === 0
    && uninvolved.length === 0 && shared.length === 0 && result.status !== 'loading'

  const abbreviations = Object.fromEntries(teams.map((t) => [t.id, t.abbreviation]))

  function changed(nextMoves) {
    setMoves(nextMoves)
    setResult(idle)
  }

  // Replace oldId in the trade: its outgoing picks go, players headed to it follow newId.
  function retarget(current, oldId, newId) {
    const next = {}
    for (const [id, m] of Object.entries(current)) {
      if (m.from === oldId) continue
      if (m.to === oldId) {
        if (newId && newId !== m.from) next[id] = { ...m, to: newId }
        continue
      }
      next[id] = m
    }
    return next
  }

  function setSlotTeam(key, teamId) {
    const slot = slots.find((s) => s.key === key)
    const nextSlots = slots.map((s) => (s.key === key ? { ...s, teamId } : s))
    const nextIds = nextSlots.map((s) => s.teamId).filter(Boolean)
    const next = retarget(moves, slot.teamId, teamId)
    // Players checked before a second team existed now get a destination.
    for (const [id, m] of Object.entries(next)) {
      if (m.to == null) next[id] = { ...m, to: defaultDestination(m.from, nextIds) }
    }
    setSlots(nextSlots)
    changed(next)
  }

  function removeSlot(key) {
    const slot = slots.find((s) => s.key === key)
    setSlots(slots.filter((s) => s.key !== key))
    changed(retarget(moves, slot.teamId, null))
  }

  // Default destination: the next team after the source, in slot order.
  function defaultDestination(fromId, ids = teamIds) {
    if (ids.length < 2) return null
    return ids[(ids.indexOf(fromId) + 1) % ids.length]
  }

  function togglePlayer(fromId, playerId) {
    const next = { ...moves }
    if (next[playerId]?.from === fromId) delete next[playerId]
    else next[playerId] = { from: fromId, to: defaultDestination(fromId) }
    changed(next)
  }

  function setDestination(playerId, to) {
    changed({ ...moves, [playerId]: { ...moves[playerId], to } })
  }

  const canRequest = (ownerId) =>
    teamIds.includes(ownerId) || slots.some((s) => !s.teamId) || slots.length < MAX_TEAMS

  // Bring a target into the trade: add the owner's team if needed and route the player here.
  function requestTarget(toId, target) {
    const owner = target.team_id
    if (owner == null || !canRequest(owner)) return
    if (!teamIds.includes(owner)) {
      const empty = slots.find((s) => !s.teamId)
      setSlots(empty
        ? slots.map((s) => (s.key === empty.key ? { ...s, teamId: owner } : s))
        : [...slots, newSlot(owner)])
    }
    changed({ ...moves, [target.player.player_id]: { from: owner, to: toId } })
  }

  function reset() {
    setSlots([newSlot(), newSlot()])
    changed({})
  }

  function copyLink() {
    navigator.clipboard?.writeText(window.location.href)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => {})
  }

  function analyze() {
    setResult({ status: 'loading' })
    analyzeTrade({ seasonId: season.id, teamIds, transfers: moveList })
      .then(({ data, meta }) => setResult({ status: 'ready', data, meta }))
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

  let hint = null
  if (ready && shared.length === 0) {
    if (moveList.length === 0) hint = 'Check at least one player to trade.'
    else if (undirected.length > 0) hint = 'Choose where each checked player goes.'
    else if (uninvolved.length > 0) {
      hint = `${uninvolved.map((id) => abbreviations[id]).join(', ')} must send or receive a player.`
    }
  }

  return (
    <section className="page trade-page">
      <h1>Trade Simulator</h1>
      <p className="muted">
        Pick up to {MAX_TEAMS} teams and check the players each one sends. Projections use{' '}
        {season ? formatSeason(season) : '…'} ratings and minutes; salary rules use the 2026–27 cap.
      </p>
      {loadError && <p className="error">{loadError.message}</p>}

      <div className="trade-builder">
        {slots.map((slot, index) => (
          <TeamColumn
            key={slot.key}
            index={index}
            slot={slot}
            teams={teams}
            takenIds={teamIds}
            tradeTeamIds={teamIds}
            roster={slot.teamId ? rosters[slot.teamId] : null}
            moves={moves}
            players={players}
            canRemove={slots.length > 2}
            onTeamChange={(id) => setSlotTeam(slot.key, id)}
            onRemove={() => removeSlot(slot.key)}
            onToggle={(playerId) => togglePlayer(slot.teamId, playerId)}
            onDestination={setDestination}
            onRequestTarget={(target) => requestTarget(slot.teamId, target)}
            canRequest={canRequest}
          />
        ))}
      </div>

      <div className="trade-actions">
        <button type="button" className="trade-button" disabled={!canAnalyze} onClick={analyze}>
          {result.status === 'loading' ? 'Analyzing…' : 'Analyze trade'}
        </button>
        {slots.length < MAX_TEAMS && (
          <button type="button" className="trade-secondary" onClick={() => setSlots([...slots, newSlot()])}>
            Add team
          </button>
        )}
        {(teamIds.length > 0 || moveList.length > 0) && (
          <>
            <button type="button" className="trade-secondary" onClick={copyLink}>
              {copied ? 'Link copied' : 'Copy link'}
            </button>
            <button type="button" className="link-button" onClick={reset}>Reset</button>
          </>
        )}
        {hint && <span className="muted">{hint}</span>}
      </div>

      {shared.length > 0 && (
        <p className="error">
          {shared.map(({ player, teams: [a, b] }) => `${player.name} (${abbreviations[a]} and ${abbreviations[b]})`).join(', ')}{' '}
          played for more than one of these teams last season, so the simulator can't split these rosters yet.
          Pick a different team.
        </p>
      )}
      {result.status === 'error' && <p className="error">{result.error.message}</p>}
      {result.status === 'ready' && (
        <div className="trade-results">
          {!result.data.analysis_available && (
            <p className="error">
              {result.data.teams.length === 0
                ? 'This trade could not be simulated. See the checks below.'
                : 'Win projections are unavailable for this trade.'}
            </p>
          )}
          {result.data.teams.length > 0 && (
            <div className="trade-builder">
              {result.data.teams.map((team) => <TeamResult key={team.team_id} team={team} players={players} />)}
            </div>
          )}
          <Legality legality={result.data.legality} abbreviations={abbreviations} />
          {result.meta?.warnings?.length > 0 && (
            <details className="trade-assumptions">
              <summary>Assumptions behind these numbers</summary>
              <ul>{result.meta.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </section>
  )
}
