// Number formatting. Currency is INR in lakh/crore, as brand managers in India read it.

export const inr = (v, digits = 1) => {
  if (v == null || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  const s = v < 0 ? '−' : ''
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(digits)} L`
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(digits)} K`
  return `${s}₹${a.toFixed(a < 100 ? 1 : 0)}`
}
// Axis ticks: whole units when the tick is whole, one decimal otherwise (so ₹1.5 L and ₹2 L stay distinct)
export const inrAxis = (v) => {
  const a = Math.abs(v)
  const unit = a >= 1e7 ? 1e7 : a >= 1e5 ? 1e5 : a >= 1e3 ? 1e3 : 1
  return inr(v, Number.isInteger(Math.round((a / unit) * 1000) / 1000) ? 0 : 1)
}
export const num = (v, d = 0) => (v == null ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }))
export const pct = (v, d = 1) => (v == null ? '—' : `${Number(v).toFixed(d)}%`)
export const signed = (v, d = 1, unit = '%') => {
  if (v == null) return '—'
  const r = Number(v.toFixed(d))
  return `${r > 0 ? '+' : r < 0 ? '−' : '±'}${Math.abs(r).toFixed(d)}${unit}`
}
export const pp = (v, d = 1) => signed(v, d, 'pp')

// Format a KPI value by its registry unit
export const byUnit = (unit, v) => {
  switch (unit) {
    case 'currency': return inr(v)
    case 'pct': return pct(v)
    case 'count': return num(v)
    case 'rating': return v == null ? '—' : `${v.toFixed(2)} ★`
    case 'index': return v == null ? '—' : v.toFixed(1)
    case 'ratio': return v == null ? '—' : `${v.toFixed(2)}×`
    default: return v == null ? '—' : String(Math.round(v * 100) / 100)
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const dateLabel = (iso, grain = 'D') => {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  if (grain === 'M') return `${MONTHS[m - 1]} ${String(y).slice(2)}`
  return `${d} ${MONTHS[m - 1]}`
}
export const longDate = (iso) => {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}
