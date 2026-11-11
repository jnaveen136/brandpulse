import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Async, Card, Delta, Note, Section, Seg, TIER, TT, TierBadge, TierLegend, axis } from '../components/ui'
import { inr, num, pct, signed } from '../format'
import { useBrandApi, useView } from '../state'

const METRICS = [
  { id: 'revenue', label: 'Revenue', fmt: inr },
  { id: 'units', label: 'Units', fmt: (v) => num(v) },
  { id: 'asp', label: 'ASP', fmt: (v) => (v == null ? '—' : `₹${v.toFixed(1)}`) },
  { id: 'margin_pct', label: 'Margin %', fmt: pct },
  { id: 'discount_pct', label: 'Discount %', fmt: (v) => pct(v, 2) },
  { id: 'avg_rating', label: 'Rating', fmt: (v) => (v == null ? '—' : `${v.toFixed(2)} ★`) },
  { id: 'revenue_growth_pct', label: 'Growth', fmt: (v) => signed(v) },
]
const ORDER = { focus: 0, self: 1, reckitt: 2, external: 3 }

function ClosestRival({ rivals }) {
  const top = rivals[0]
  const max = Math.max(...rivals.map((r) => r.variants_overlapped))
  return (
    <Card title="Closest external rival" sub="External brands ranked by how many of our variants they compete with (same sub-category)">
      {top && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{top.RivalBrand} <span className="faint small" style={{ fontWeight: 500 }}>{top.RivalManufacturer}</span></div>
          <div className="muted small">Competes with {top.variants_overlapped} of {top.total_variants} variants · in {top.subcategories.join(', ')} · {inr(top.shared_subcategory_revenue)} revenue in those sub-categories</div>
        </div>
      )}
      {rivals.map((r) => (
        <div className="rbar-row" key={r.RivalBrand} title={`${r.RivalBrand}: ${r.subcategories.join(', ')}`}>
          <span>{r.RivalBrand}</span>
          <div className="rbar-track"><div className="rbar" style={{ width: `${(100 * r.variants_overlapped) / max}%` }} /></div>
          <span className="num small" style={{ textAlign: 'right' }}>{r.variants_overlapped}/{r.total_variants}</span>
        </div>
      ))}
      <p className="faint small" style={{ marginTop: 8 }}>Ties are broken by the rival's revenue in the shared sub-categories.</p>
    </Card>
  )
}

function Matrix({ matrix }) {
  return (
    <Card title="Who competes with which variant" sub="● = that external brand sells in the variant's sub-category">
      <div className="tbl-wrap">
        <table className="matrix">
          <thead>
            <tr><th>Variant</th>{matrix.brands.map((b) => <th key={b} className="r" style={{ textAlign: 'center' }}>{b}</th>)}</tr>
          </thead>
          <tbody>
            {matrix.rows.map((r) => (
              <tr key={r.ProductID}>
                <td><div>{r.ProductName}</div><div className="faint small">{r.SubCategory}</div></td>
                {matrix.brands.map((b) => (
                  <td key={b} className="dotc"><i className={`dot ${r.cells[b] ? '' : 'off'}`} aria-label={r.cells[b] ? 'competes' : 'no'} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function VariantCard({ v, metric, brand }) {
  const m = METRICS.find((x) => x.id === metric)
  const rows = [
    { name: v.ProductName, brand, tier: 'focus', value: v[metric] },
    ...v.rivals.map((r) => ({ name: r.ProductName, brand: r.Brand, tier: r.Tier, value: r[metric], category: r.Category })),
  ].sort((a, b) => ORDER[a.tier] - ORDER[b.tier] || (b.value ?? -Infinity) - (a.value ?? -Infinity))
  const ext = v.rivals.filter((r) => r.Tier === 'external').length
  const neg = rows.some((r) => (r.value ?? 0) < 0)
  return (
    <div className="variant-card">
      <div className="v-head">
        <h3>{v.ProductName} <span className="faint small" style={{ fontWeight: 500 }}>· {v.Category} · MRP ₹{v.MRP}</span></h3>
        <span className="small muted">{ext} external rival SKU{ext === 1 ? '' : 's'}: {v.external_brands.join(', ') || 'none'}</span>
      </div>
      <div className="v-stats">
        <div><span className="l">Revenue</span><span className="v num">{inr(v.revenue)}</span></div>
        <div><span className="l">Growth</span><span className="v"><Delta value={v.revenue_growth_pct} /></span></div>
        <div><span className="l">Units</span><span className="v num">{num(v.units)}</span></div>
        <div><span className="l">ASP</span><span className="v num">₹{v.asp?.toFixed(1)}</span></div>
        <div><span className="l">Margin</span><span className="v num">{pct(v.margin_pct)}</span></div>
        <div><span className="l">Rating</span><span className="v num">{v.avg_rating?.toFixed(2)} ★</span></div>
        <div title="Our ASP vs the external rivals' combined ASP in this sub-category">
          <span className="l">Price gap vs rivals</span>
          <span className="v num">{v.price_gap_pct == null ? '—' : signed(v.price_gap_pct)}</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={rows.length * 28 + 24}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 80, bottom: 0, left: 0 }} barCategoryGap={5}>
          <CartesianGrid stroke="var(--grid)" horizontal={false} />
          <XAxis type="number" {...axis} tickFormatter={(v) => m.fmt(v)} domain={neg ? ['auto', 'auto'] : [0, 'auto']} />
          <YAxis type="category" dataKey="name" width={190} {...axis}
            tick={({ x, y, payload, index }) => {
              const r = rows[index]
              return (
                <text x={x} y={y} dy={4} textAnchor="end" fontSize={12} fill="var(--text)" fontWeight={r?.tier === 'focus' ? 700 : 400}>
                  {payload.value}
                </text>
              )
            }} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const d = payload[0].payload
            return <TT title={d.name} rows={[{ label: TIER[d.tier].label, value: '', color: TIER[d.tier].color }, { label: m.label, value: m.fmt(d.value) }]} />
          }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}
            label={{ position: 'right', formatter: (v) => m.fmt(v), fontSize: 11, fill: 'var(--text-2)' }}>
            {rows.map((r, i) => <Cell key={i} fill={TIER[r.tier].color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <details style={{ marginTop: 6 }}>
        <summary className="small muted" style={{ cursor: 'pointer' }}>Rival list ({v.rivals.length})</summary>
        <div className="tbl-wrap" style={{ marginTop: 6 }}>
          <table>
            <thead><tr><th>Product</th><th>Tier</th><th>Brand</th><th>Category</th>{METRICS.map((x) => <th key={x.id} className="r">{x.label}</th>)}</tr></thead>
            <tbody>
              {v.rivals.map((r) => (
                <tr key={r.ProductID}>
                  <td>{r.ProductName}</td><td><TierBadge tier={r.Tier} /></td><td>{r.Brand}</td><td className="muted">{r.Category}</td>
                  {METRICS.map((x) => <td key={x.id} className="r num">{x.fmt(r[x.id])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

export default function Variants() {
  const state = useBrandApi('variants')
  const { view } = useView()
  const [metric, setMetric] = useState('revenue')
  return (
    <Async state={state}>
      {(d) => (
        <>
          <div className="grid g2">
            <ClosestRival rivals={d.closest_rivals} />
            <Matrix matrix={d.matrix} />
          </div>
          <div className="card" style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center', position: 'sticky', top: 0, zIndex: 5 }}>
            <TierLegend />
            <Seg options={METRICS.map(({ id, label }) => ({ id, label }))} value={metric} onChange={setMetric} />
          </div>
          {d.groups.map((g) => (
            <Section key={g.SubCategory} title={g.SubCategory}
              sub={`${g.variants.length} ${view.brand} variant${g.variants.length > 1 ? 's' : ''} in this sub-category. Each is compared with every other SKU in ${g.SubCategory}, whatever its category.`}>
              <Card>{g.variants.map((v) => <VariantCard key={v.ProductID} v={v} metric={metric} brand={view.brand} />)}</Card>
            </Section>
          ))}
          <div style={{ marginTop: 18 }}>
            <Note>Competitors are matched on sub-category only (agreed rule). Category labels differ within a brand in this data, so matching on category would pair unrelated products.</Note>
          </div>
        </>
      )}
    </Async>
  )
}
