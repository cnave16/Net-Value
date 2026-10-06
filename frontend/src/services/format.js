// Display helpers. null means "no data", never zero.

const money = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
})

export function formatMoney(value, missing = 'Unavailable') {
  return value == null ? missing : money.format(value)
}

export function formatSurplus(value, missing = 'Unavailable') {
  if (value == null) return missing
  return `${value >= 0 ? '+' : '−'}${money.format(Math.abs(value))}`
}

export function formatRating(value) {
  if (value == null) return '—'
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}`
}

export function formatSeason({ start_year, end_year }) {
  return `${start_year}–${String(end_year).slice(-2)}`
}
