import { useEffect, useState } from 'react'
import { getPicks, USE_MOCK } from '../services/api.js'
import { formatMoney, formatSurplus } from '../services/format.js'

// Draft pick value by slot: Chase's fair-value model averaged over past picks at
// each slot (backend/services/draft.py), against this year's rookie salary there
// over the same contract seasons. "Typical" is the median outcome.

const CHART_HEIGHT = 260
const PAD = { top: 12, right: 8, bottom: 28, left: 52 }

function niceMax(value) {
  const step = 10_000_000
  return Math.max(step, Math.ceil(value / step) * step)
}

function ValueChart({ picks }) {
  const [active, setActive] = useState(null)
  const width = 1100
  const innerW = width - PAD.left - PAD.right
  const innerH = CHART_HEIGHT - PAD.top - PAD.bottom
  const max = niceMax(Math.max(...picks.map((p) => Math.max(p.expected_value_per_season, p.salary_per_season ?? 0))))
  const slotW = innerW / picks.length
  const barW = Math.min(24, slotW - 4)
  const y = (v) => PAD.top + innerH - (v / max) * innerH
  const ticks = Array.from({ length: max / 10_000_000 + 1 }, (_, i) => i * 10_000_000)
  const roundTwoX = PAD.left + 30 * slotW
  const hovered = active == null ? null : picks[active]

  return (
    <div className="draft-chart">
      <div className="draft-legend" aria-hidden="true">
        <span><i className="key-bar" />Expected value per season</span>
        <span><i className="key-tick" />Rookie salary per season</span>
      </div>
      <div className="draft-chart-frame" onPointerLeave={() => setActive(null)}>
        <svg viewBox={`0 0 ${width} ${CHART_HEIGHT}`} role="img"
          aria-label="Expected value per season and rookie salary for draft picks 1 to 60. The table below lists every value.">
          {ticks.map((t) => (
            <g key={t}>
              <line className="draft-grid" x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="draft-axis" x={PAD.left - 8} y={y(t) + 4} textAnchor="end">{t === 0 ? '$0' : `$${t / 1e6}M`}</text>
            </g>
          ))}
          <line className="draft-divider" x1={roundTwoX} x2={roundTwoX} y1={PAD.top} y2={PAD.top + innerH} />
          <text className="draft-axis" x={roundTwoX + 6} y={PAD.top + 10}>Round 2</text>
          {picks.map((p, i) => {
            const cx = PAD.left + i * slotW + slotW / 2
            const top = y(p.expected_value_per_season)
            const h = PAD.top + innerH - top
            const r = Math.min(4, h, barW / 2)
            return (
              <g key={p.pick} className={active === i ? 'draft-slot active' : 'draft-slot'}>
                {/* 4px rounded data end, square at the baseline. */}
                <path className="draft-bar" d={`M${cx - barW / 2},${top + h} V${top + r} Q${cx - barW / 2},${top} ${cx - barW / 2 + r},${top} H${cx + barW / 2 - r} Q${cx + barW / 2},${top} ${cx + barW / 2},${top + r} V${top + h} Z`} />
                {p.salary_per_season != null && (
                  <line className={p.salary_is_estimate ? 'draft-tick estimate' : 'draft-tick'}
                    x1={cx - barW / 2 - 2} x2={cx + barW / 2 + 2} y1={y(p.salary_per_season)} y2={y(p.salary_per_season)} />
                )}
                {(p.pick === 1 || p.pick % 10 === 0) && (
                  <text className="draft-axis" x={cx} y={CHART_HEIGHT - 8} textAnchor="middle">{p.pick}</text>
                )}
                <rect className="draft-hit" x={PAD.left + i * slotW} y={PAD.top} width={slotW} height={innerH}
                  tabIndex={0} aria-label={`Pick ${p.pick}`}
                  onPointerEnter={() => setActive(i)} onFocus={() => setActive(i)} onBlur={() => setActive(null)} />
              </g>
            )
          })}
        </svg>
        {hovered && (
          <div className="draft-tooltip" style={{ left: `${((PAD.left + active * slotW + slotW / 2) / width) * 100}%` }}>
            <small>Pick {hovered.pick}{hovered.current_draftee ? ` · ${hovered.current_draftee.name}` : ''}</small>
            <div><i className="key-bar" /><strong>{formatMoney(hovered.expected_value_per_season)}</strong> average value per season</div>
            <div><i className="key-tick" /><strong>{formatMoney(hovered.salary_per_season)}</strong> salary per season{hovered.salary_is_estimate ? ' (estimated)' : ''}</div>
            <div className="muted">{formatSurplus(hovered.surplus_per_season)} average surplus</div>
            <div className="muted">{formatMoney(hovered.typical_value_per_season)} typical value ({formatSurplus(hovered.typical_surplus_per_season)})</div>
          </div>
        )}
      </div>
      <p className="fine muted">Pick number. A dashed tick means some of that slot&apos;s salary is interpolated from neighboring picks.</p>
    </div>
  )
}

function PickTable({ picks }) {
  const [showRoundTwo, setShowRoundTwo] = useState(false)
  const rows = showRoundTwo ? picks : picks.filter((p) => p.round === 1)
  return (
    <div className="draft-table-wrap">
      <table className="draft-table">
        <thead>
          <tr>
            <th>Pick</th><th>2026 pick</th><th>Average value</th><th>Typical value</th><th>Salary</th><th>Average surplus</th><th>Typical surplus</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.pick}>
              <td>{p.pick}</td>
              <td>{p.current_draftee?.name ?? '—'}</td>
              <td>{formatMoney(p.expected_value_per_season)}</td>
              <td>{formatMoney(p.typical_value_per_season)}</td>
              <td>{p.salary_is_estimate ? '≈ ' : ''}{formatMoney(p.salary_per_season)}</td>
              <td className={p.surplus_per_season >= 0 ? 'positive' : 'negative'}>{formatSurplus(p.surplus_per_season)}</td>
              <td className={p.typical_surplus_per_season >= 0 ? 'positive' : 'negative'}>{formatSurplus(p.typical_surplus_per_season)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="link-button" onClick={() => setShowRoundTwo((v) => !v)}>
        {showRoundTwo ? 'Hide round 2' : 'Show round 2'}
      </button>
    </div>
  )
}

export default function DraftPage() {
  const [state, setState] = useState({ status: USE_MOCK ? 'mock' : 'loading' })

  useEffect(() => {
    if (USE_MOCK) return
    getPicks()
      .then(({ data, meta }) => setState({ status: 'ready', picks: data, meta }))
      .catch((error) => setState({ status: 'error', error }))
  }, [])

  if (state.status === 'mock') {
    return (
      <section className="page">
        <h1>Draft Pick Value</h1>
        <p className="muted">Draft values need the live backend. Set VITE_USE_MOCK=false in frontend/.env.local and restart Vite.</p>
      </section>
    )
  }

  const { picks, meta } = state
  const first = picks?.[0]
  const tenth = picks?.[9]
  const assumptions = meta?.assumptions

  return (
    <section className="page draft-page">
      <h1>Draft Pick Value</h1>
      <p className="muted">
        What each draft slot is worth: the fair value past picks at that slot produced in their first
        seasons (Chase&apos;s fair-value model on {meta ? `${meta.stats_season_end_year - 1}–${String(meta.stats_season_end_year).slice(-2)}` : '…'} stats),
        against what this year&apos;s rookie at that slot is paid over the same seasons.
      </p>
      {state.status === 'loading' && <p className="muted">Loading draft values…</p>}
      {state.status === 'error' && <p className="error">{state.error.message}</p>}
      {state.status === 'ready' && (
        <>
          <div className="draft-tiles">
            <div className="stat"><small>No. 1 pick, per season</small><strong>{formatMoney(first.expected_value_per_season)}</strong><span className="fine muted">vs {formatMoney(first.salary_per_season)} salary per season</span></div>
            <div className="stat"><small>No. 10 pick, per season</small><strong>{formatMoney(tenth.expected_value_per_season)}</strong><span className="fine muted">vs {formatMoney(tenth.salary_per_season)} salary per season</span></div>
            <div className="stat"><small>Typical pick beats its salary</small><strong>{picks.filter((p) => p.typical_surplus_per_season >= 0).length} of {picks.length}</strong><span className="fine muted">slots (median outcome)</span></div>
          </div>
          <ValueChart picks={picks} />
          <PickTable picks={picks} />
          <details className="trade-assumptions" open>
            <summary>How this is calculated</summary>
            <ul>
              <li>
                Based on {meta.sample_size} players from the {meta.history_classes[0]}–{meta.history_classes.at(-1)} drafts,
                valued by Chase&apos;s model in one season and smoothed across nearby slots.
              </li>
              <li>
                Value and salary both count {assumptions.contract_seasons['1']} seasons for first-round picks and {assumptions.contract_seasons['2']} for
                second-round picks. Salary is what this year&apos;s pick at that slot is paid over those seasons; unsigned slots
                and shorter deals use neighboring picks&apos; salaries (≈).
              </li>
              <li>
                Average value is what a pick is worth in expectation, including the rare stars. Typical value is the
                median outcome: what most players drafted at that slot turn into.
              </li>
              <li>Drafted players who never played count as the {formatMoney(assumptions.washout_value)} minimum.</li>
              <li>These are placeholder assumptions pending review of the fair-value model.</li>
            </ul>
          </details>
        </>
      )}
    </section>
  )
}
