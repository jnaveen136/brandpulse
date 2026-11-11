import { useEffect, useRef, useState } from 'react'
import { longDate } from './format'
import { useApi, useView } from './state'
import { Loading, ErrorBox } from './components/ui'
import Overview from './pages/Overview'
import Variants from './pages/Variants'
import Competitors from './pages/Competitors'
import Retailers from './pages/Retailers'
import Marketing from './pages/Marketing'
import Diagnostics from './pages/Diagnostics'
import Ask from './pages/Ask'

const PAGES = [
  { id: 'overview', label: 'Overview', el: Overview, sub: 'How the brand is doing' },
  { id: 'variants', label: 'Variants & Competitors', el: Variants, sub: 'Every variant against its real rivals' },
  { id: 'competitors', label: 'Competitor Intelligence', el: Competitors, sub: 'Price, discount, share and activity vs rivals' },
  { id: 'retailers', label: 'Retailer Performance', el: Retailers, sub: 'Where the brand sells and how well' },
  { id: 'marketing', label: 'Marketing & Promotions', el: Marketing, sub: 'Promotion effectiveness and campaign spend' },
  { id: 'diagnostics', label: 'Diagnostics', el: Diagnostics, sub: 'Why revenue moved' },
  { id: 'ask', label: 'Ask the Data', el: Ask, sub: 'Questions answered from the KPI engine' },
]

function MultiSelect({ label, options, value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const toggle = (o) => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])
  return (
    <div className="control ms" ref={ref}>
      <label>{label}</label>
      <button className="ms-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        {value.length === 0 ? 'All' : value.length === 1 ? value[0] : `${value.length} selected`} ▾
      </button>
      {open && (
        <div className="ms-pop">
          {options.map((o) => (
            <label key={o}><input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} />{o}</label>
          ))}
          {value.length > 0 && <button className="btn ghost small" style={{ width: '100%', marginTop: 4 }} onClick={() => onChange([])}>Clear</button>}
        </div>
      )}
    </div>
  )
}

function TopBar({ meta, page }) {
  const { view, set } = useView()
  // a light request just to show the resolved date ranges
  const period = useApi(`/api/kpi/revenue?brands=${encodeURIComponent(view.brand)}&period=${view.period}&mode=${view.mode}`)
  const p = period.data
  const fo = meta.filter_options
  const active = ['retailers', 'channels', 'tiers', 'regions'].flatMap((k) => view[k].map((v) => [k, v]))
  return (
    <div className="topbar">
      <div className="title-row">
        <div>
          <h1>{view.brand} <span className="faint" style={{ fontWeight: 500 }}>· {page.label}</span></h1>
          <p className="muted small">{page.sub}</p>
        </div>
        <div className="brand-pills" role="radiogroup" aria-label="Core brand">
          {meta.core_brands.map((b) => (
            <button key={b.brand} role="radio" aria-checked={view.brand === b.brand}
              className={`pill ${view.brand === b.brand ? 'active' : ''}`} onClick={() => set({ brand: b.brand })}>
              {b.brand}
            </button>
          ))}
        </div>
      </div>
      <div className="controls">
        <div className="control">
          <label>Period</label>
          <select value={view.period} onChange={(e) => set({ period: e.target.value })}>
            {meta.presets.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>
        <div className="control">
          <label>Compare with</label>
          <select value={view.mode} onChange={(e) => set({ mode: e.target.value })}>
            {meta.compare_modes.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>
        <MultiSelect label="Retailer" options={fo.retailers} value={view.retailers} onChange={(v) => set({ retailers: v })} />
        <MultiSelect label="Channel" options={fo.channels} value={view.channels} onChange={(v) => set({ channels: v })} />
        <MultiSelect label="Tier" options={fo.tiers} value={view.tiers} onChange={(v) => set({ tiers: v })} />
        <MultiSelect label="Region" options={fo.regions} value={view.regions} onChange={(v) => set({ regions: v })} />
        {p && (
          <div className="range-note" style={{ alignSelf: 'flex-end', paddingBottom: 6 }}>
            <strong>{longDate(p.period.start)} – {longDate(p.period.end)}</strong>
            {p.comparison && <> vs {longDate(p.comparison.start)} – {longDate(p.comparison.end)}</>}
            {p.comparison_coverage != null && p.comparison_coverage < 1 &&
              <span className="badge proxy" style={{ marginLeft: 6 }}>{p.comparison_coverage === 0 ? 'no comparison data' : 'comparison partly outside data'}</span>}
          </div>
        )}
      </div>
      {active.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {active.map(([k, v]) => (
            <span className="chip" key={k + v}>{v}<button aria-label={`Remove ${v}`} onClick={() => set({ [k]: view[k].filter((x) => x !== v) })}>✕</button></span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const meta = useApi('/api/meta')
  const { view, set } = useView()
  const page = PAGES.find((p) => p.id === view.page) || PAGES[0]
  const Page = page.el
  return (
    <div className="shell">
      <aside className="side">
        <div className="logo"><span className="logo-mark">◆</span>BrandPulse</div>
        <nav className="nav">
          {PAGES.map((p) => (
            <button key={p.id} className={p.id === page.id ? 'active' : ''} onClick={() => set({ page: p.id })}>{p.label}</button>
          ))}
        </nav>
        <div className="side-foot">
          Reckitt core brands vs Unilever & P&G rivals.<br />
          {meta.data && <>Data: {longDate(meta.data.data_range.start)} – {longDate(meta.data.data_range.end)}</>}
        </div>
      </aside>
      <main className="main">
        {meta.error && <ErrorBox error={`${meta.error}. Is the API running? (make api)`} />}
        {!meta.data && !meta.error && <Loading />}
        {meta.data && (
          <>
            <TopBar meta={meta.data} page={page} />
            <Page meta={meta.data} key={page.id} />
          </>
        )}
      </main>
    </div>
  )
}
