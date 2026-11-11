import { byUnit, pp, signed } from '../format'

export function Card({ title, sub, right, children, className = '', style }) {
  return (
    <div className={`card ${className}`} style={style}>
      {(title || right) && (
        <div className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

export function Section({ title, sub, children }) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {sub && <p className="card-sub">{sub}</p>}
      {children}
    </section>
  )
}

/** Change indicator. Colour + arrow + sign, so it never relies on colour alone. */
export function Delta({ value, kind = 'pct', higherIsBetter = true, digits = 1, suffix = '' }) {
  if (value == null) return <span className="delta flat">no comparison</span>
  const flat = Math.abs(value) < 0.05
  const good = flat || higherIsBetter == null ? null : (value > 0) === higherIsBetter
  const cls = good == null ? 'flat' : good ? 'good' : 'bad'
  const arrow = flat ? '→' : value > 0 ? '▲' : '▼'
  const text = kind === 'pp' ? pp(value, digits) : kind === 'abs' ? signed(value, digits, '') : signed(value, digits)
  return (
    <span className={`delta ${cls}`} title={good == null ? 'No change' : good ? 'Favourable' : 'Unfavourable'}>
      <span aria-hidden>{arrow}</span> {text}{suffix}
    </span>
  )
}

/** One KPI from the engine's compare() payload. Percent KPIs show change in pp. */
export function KpiCard({ k, label }) {
  const isPct = k.unit === 'pct'
  const change = isPct ? k.delta : k.delta_pct
  return (
    <div className="card">
      <div className="kpi-label">{label || k.name}</div>
      <div className="kpi-value num">{byUnit(k.unit, k.current)}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <Delta value={change} kind={isPct ? 'pp' : 'pct'} higherIsBetter={k.higher_is_better} />
        {k.previous != null && <span className="kpi-prev num">vs {byUnit(k.unit, k.previous)}</span>}
      </div>
      {k.ignored_filters?.length > 0 && <div className="kpi-prev">filters not applicable: {k.ignored_filters.join(', ')}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading…' }) {
  return <div className="loading">{label}</div>
}

export function ErrorBox({ error }) {
  return <div className="error">Couldn't load this view: {error}</div>
}

/** Wraps a page: shows loading/error, and dims stale content while refetching. */
export function Async({ state, children }) {
  if (state.error) return <ErrorBox error={state.error} />
  if (!state.data) return <Loading />
  return <div className={state.loading ? 'skeleton' : ''}>{children(state.data)}</div>
}

export function Note({ children, icon = 'ℹ' }) {
  return (
    <div className="note">
      <span aria-hidden>{icon}</span>
      <span>{children}</span>
    </div>
  )
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.id} className={value === o.id ? 'active' : ''} onClick={() => onChange(o.id)} role="tab" aria-selected={value === o.id}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export const TIER = {
  focus: { color: 'var(--focus)', label: 'This variant' },
  self: { color: 'var(--sibling)', label: 'Same brand, other variants' },
  reckitt: { color: 'var(--reckitt)', label: 'Other Reckitt brands' },
  external: { color: 'var(--external)', label: 'External competitors (Unilever / P&G)' },
}

export function TierLegend() {
  return (
    <div className="legend">
      {Object.entries(TIER).map(([k, t]) => (
        <span key={k}><i className="sw" style={{ background: t.color }} />{t.label}</span>
      ))}
    </div>
  )
}

export function TierBadge({ tier }) {
  const map = { external: ['ext', 'External'], reckitt: ['rk', 'Reckitt'], self: ['self', 'Same brand'] }
  const [cls, label] = map[tier] || ['self', tier]
  return <span className={`badge ${cls}`}>{label}</span>
}

/** Recharts tooltip in the app's style. rows: [{label, value, color, dashed}] */
export function TT({ title, rows }) {
  return (
    <div className="tt">
      {title && <div className="tt-title">{title}</div>}
      {rows.map((r, i) => (
        <div className="tt-row" key={i}>
          <span>{r.color && <i className={`sw ${r.dashed ? 'dash' : ''}`} style={{ background: r.color }} />}{r.label}</span>
          <span className="num" style={{ fontWeight: 600 }}>{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export const axis = { stroke: 'var(--text-3)', fontSize: 11, tickLine: false, axisLine: false }
