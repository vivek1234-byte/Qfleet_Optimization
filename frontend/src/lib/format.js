/** Number, currency and date formatting shared by every page. */

const nf = (options) => new Intl.NumberFormat('en-US', options)

const compactFmt = nf({ notation: 'compact', maximumFractionDigits: 1 })
const usdFmt = nf({ style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usdCompactFmt = nf({
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
})

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)

export function num(value, decimals = 0) {
  if (!isNumber(value)) return '—'
  return nf({ minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value)
}

export function compact(value) {
  return isNumber(value) ? compactFmt.format(value) : '—'
}

export function usd(value, { compact: useCompact = false } = {}) {
  if (!isNumber(value)) return '—'
  return useCompact ? usdCompactFmt.format(value) : usdFmt.format(value)
}

export function pct(value, decimals = 1) {
  if (!isNumber(value)) return '—'
  return `${value.toFixed(decimals)}%`
}

/** Signed percentage, for deltas where the direction is the point. */
export function signedPct(value, decimals = 1) {
  if (!isNumber(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

export function tons(value, decimals = 0) {
  return isNumber(value) ? `${num(value, decimals)} t` : '—'
}

export function seconds(value) {
  if (!isNumber(value)) return '—'
  if (value < 1) return `${Math.round(value * 1000)} ms`
  return `${value.toFixed(2)} s`
}

export function timeAgo(epochSeconds) {
  if (!isNumber(epochSeconds) || epochSeconds <= 0) return 'never'
  const deltaSeconds = Math.round(Date.now() / 1000 - epochSeconds)
  const steps = [
    [60, 'second', 1],
    [3600, 'minute', 60],
    [86400, 'hour', 3600],
    [2592000, 'day', 86400],
  ]
  for (const [limit, unit, divisor] of steps) {
    if (deltaSeconds < limit) {
      const amount = Math.max(Math.floor(deltaSeconds / divisor), 0)
      return amount <= 1 ? `just now` : `${amount} ${unit}s ago`
    }
  }
  return new Date(epochSeconds * 1000).toLocaleDateString()
}

/** Human label for a backend objective key. */
export const OBJECTIVE_LABELS = {
  fuel_consumption_tons: 'Fuel',
  co2_emissions_tons: 'CO₂e',
  operational_cost_usd: 'Cost',
}

export const OBJECTIVE_UNITS = {
  fuel_consumption_tons: 't',
  co2_emissions_tons: 't',
  operational_cost_usd: 'USD',
}

export function formatObjective(key, value) {
  if (!isNumber(value)) return '—'
  return key === 'operational_cost_usd' ? usd(value, { compact: true }) : `${compact(value)} t`
}
