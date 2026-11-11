import { useState } from 'react'
import { HBars, TrendChart } from '../components/charts'
import { Async, Card, Delta, KpiCard, Note, Section, Seg } from '../components/ui'
import { inr, num, pct, signed } from '../format'
import { useBrandApi, useView } from '../state'

const DIMS = [
  { id: 'SubCategory', label: 'Sub-category' }, { id: 'Category', label: 'Category' },
  { id: 'Retailer', label: 'Retailer' }, { id: 'Region', label: 'Region' }, { id: 'Channel', label: 'Channel' },
]
const COMPONENTS = [
  { id: 'growth', label: 'Growth', raw: (h) => signed(h.growth), hint: 'Revenue YoY %' },
  { id: 'margin', label: 'Margin', raw: (h) => pct(h.margin), hint: 'Margin %' },
  { id: 'rating', label: 'Rating', raw: (h) => `${h.rating?.toFixed(2)} ★`, hint: 'Average rating' },
  { id: 'position', label: 'Position', raw: (h) => signed(h.position, 2, 'pp'), hint: 'Market position change' },
]

function Health({ h, weights }) {
  const proxy = h.position_source === 'proxy'
  return (
    <Card title="Brand Health Score" sub={`Rank ${h.rank} of 11 brands · 50 = average brand`}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <span className="hs-big num">{h.health_score?.toFixed(0)}</span>
        <span className="muted">/ 100</span>
      </div>
      {COMPONENTS.map((c) => (
        <div key={c.id}>
          <div className="hbar" title={`${c.hint}: ${c.raw(h)} → score ${h[`${c.id}_score`]?.toFixed(0)}`}>
            <span>{c.label} <span className="faint small">{Math.round(weights[c.id] * 100)}%</span></span>
            <div className="hbar-track"><div className="hbar-fill" style={{ width: `${h[`${c.id}_score`]}%` }} /><div className="hbar-mid" /></div>
            <span className="num small" style={{ textAlign: 'right' }}>{h[`${c.id}_score`]?.toFixed(0)}</span>
          </div>
          <div className="faint small" style={{ margin: '-4px 0 6px 100px' }}>
            {c.raw(h)}
            {c.id === 'position' && <> · <span className={`badge ${proxy ? 'proxy' : 'real'}`}>{proxy ? 'proxy' : 'market share'}</span></>}
          </div>
        </div>
      ))}
      {proxy && (
        <Note>No market-share data for this brand. Position uses the change in Premium Retailer Share (Tier-1 revenue share), scored only against other proxy brands.</Note>
      )}
    </Card>
  )
}

function Breakdown({ breakdowns }) {
  const [dim, setDim] = useState('SubCategory')
  const rows = (breakdowns[dim] || []).map((r) => ({ name: r[dim], value: r.current, prev: r.previous, chg: r.delta_pct }))
  return (
    <Card title="Revenue breakdown" sub="This brand only. Hover a bar for the comparison." right={<Seg options={DIMS} value={dim} onChange={setDim} />}>
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <HBars rows={rows} extra={(d) => [{ label: 'Comparison', value: inr(d.prev) }, { label: 'Change', value: signed(d.chg) }]} />
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>{DIMS.find((d) => d.id === dim).label}</th><th className="r">Share</th><th className="r">Change</th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const tot = rows.reduce((s, x) => s + (x.value || 0), 0)
                return (
                  <tr key={r.name}>
                    <td>{r.name}</td>
                    <td className="r num">{pct((100 * (r.value || 0)) / tot)}</td>
                    <td className="r"><Delta value={r.chg} /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  )
}

export default function Overview() {
  const state = useBrandApi('overview')
  const { view } = useView()
  const [metric, setMetric] = useState('revenue')
  return (
    <Async state={state}>
      {(d) => {
        const k = Object.fromEntries(d.kpis.map((x) => [x.kpi, x]))
        const prevLabel = d.comparison?.label || 'Comparison'
        return (
          <>
            <div className="grid g5">
              {['revenue', 'units', 'asp', 'margin_pct', 'discount_pct'].map((id) => <KpiCard key={id} k={k[id]} />)}
            </div>
            <div className="grid g4" style={{ marginTop: 14 }}>
              {['margin', 'promo_revenue_share', 'avg_rating', 'stockout_risk_pct'].map((id) => <KpiCard key={id} k={k[id]} />)}
            </div>

            <div className="grid g3" style={{ marginTop: 14 }}>
              <Card className="span2" title={metric === 'revenue' ? 'Revenue trend' : 'Units trend'}
                sub={`${view.brand}, ${d.period.label.toLowerCase()} vs ${prevLabel.toLowerCase()}`}
                right={<Seg options={[{ id: 'revenue', label: 'Revenue' }, { id: 'units', label: 'Units' }]} value={metric} onChange={setMetric} />}>
                {metric === 'revenue'
                  ? <TrendChart trend={d.trend} prevLabel={prevLabel} />
                  : <TrendChart trend={d.units_trend} fmt={(v) => num(v)} axisFmt={(v) => num(v)} prevLabel={prevLabel} />}
              </Card>
              <Health h={d.health} weights={d.health_weights} />
            </div>

            <Section title="Where the revenue comes from">
              <Breakdown breakdowns={d.breakdowns} />
            </Section>
          </>
        )
      }}
    </Async>
  )
}
