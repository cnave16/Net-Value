// Display helpers. null means "no data", never zero.

const money = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
})

export function formatMoney(value) {
  return value == null ? 'Unavailable' : money.format(value)
}

export function formatSurplus(value) {
  if (value == null) return 'Unavailable'
  return `${value >= 0 ? '+' : '−'}${money.format(Math.abs(value))}`
}
