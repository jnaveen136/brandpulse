import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Async, Card, Delta, Note, Section, TT, axis } from '../components/ui'
import { inr, inrAxis } from '../format'
import { useBrandApi, useView } from '../state'
import Narrative from '../components/Narrative'

function Waterfall({ d }) {
  let run = d.revenue_prev
  const steps = [{ name: 'Comparison', base: 0, value: d.revenue_prev, kind: 'total' }]
  for (const b of d.bridge) {
    const v = b.value || 0
    steps.push({ name: b.name, base: v >= 0 ? run : run + v, value: Math.abs(v), signed: v, kind: v >= 0 ? 'up' : 'down', text: b.text })
    run += v
  }
  steps.push({ name: 'This period', base: 0, value: d.revenue, kind: 'now' })
  const color = { total: 'var(--previous)', now: 'var(--focus)', up: 'var(--focus)', down: 'var(--external)' }
  // zoom the axis onto the range the bridge moves through; totals are clipped (axis says so)
  const levels = [d.revenue_prev, d.revenue, ...steps.filter((s) => s.kind === 'up' || s.kind === 'down').flatMap((s) => [s.base, s.base + s.value])]
  const span = Math.max(...levels) - Math.min(...levels) || Math.abs(d.revenue) * 0.05
  const lo = Math.max(0, Math.min(...levels) - span * 0.6)
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={steps} margin={{ top: 22, right: 10, bottom: 0, left: 4 }} barCategoryGap="28%">
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="name" {...axis} tick={{ fill: 'var(--text)', fontSize: 12 }} />
        <YAxis {...axis} tickFormatter={(v) => inrAxis(v)} width={70} domain={[lo, Math.max(...levels) + span * 0.25]} allowDataOverflow />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null
          const s = payload[0].payload
          return <TT title={s.name} rows={[{ label: s.kind === 'up' || s.kind === 'down' ? 'Effect' : 'Revenue', value: s.signed != null ? (s.signed >= 0 ? '+' : '') + inr(s.signed) : inr(s.value) }, ...(s.text ? [{ label: s.text, value: '' }] : [])]} />
        }} />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="value" stackId="w" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {steps.map((s, i) => <Cell key={i} fill={color[s.kind]} />)}
          <LabelList dataKey="value" position="top" fontSize={11} fill="var(--text-2)"
            formatter={(v) => v} content={({ x, y, width, index }) => {
              const s = steps[index]
              const t = s.signed != null ? (s.signed >= 0 ? '+' : '') + inr(s.signed) : inr(s.value)
              return <text x={x + width / 2} y={y - 6} textAnchor="middle" fontSize={11} fill="var(--text-2)">{t}</text>
            }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

function Cause({ c }) {
  const icon = !c.supporting ? ['no', '–', 'Not a driver of this change'] : c.effect < 0 ? ['yes', '▼', 'Pushed revenue down'] : ['up', '▲', 'Pushed revenue up']
  return (
    <div className={`cause ${c.supporting ? '' : 'dim'}`}>
      <span className={`cause-icon ${icon[0]}`} title={icon[2]} aria-label={icon[2]}>{icon[1]}</span>
      <div>
        <div className="cause-title">{c.title} {c.supporting && <span className="faint small" style={{ fontWeight: 500 }}>· {icon[2].toLowerCase()}</span>}</div>
        <div className="small muted" style={{ marginTop: 2 }}>{c.text}</div>
      </div>
      <div className="num small" style={{ textAlign: 'right' }}>
        {c.impact != null && <><div style={{ fontWeight: 600 }}>{(c.impact >= 0 ? '+' : '') + inr(c.impact)}</div>
          {c.share_of_change != null && <div className="faint">{Math.round(c.share_of_change * 100)}% of change</div>}</>}
      </div>
    </div>
  )
}

function Contributors({ title, rows }) {
  return (
    <Card title={title}>
      <table>
        <tbody>{rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            <td className="r num">{(r.change >= 0 ? '+' : '') + inr(r.change)}</td>
            <td className="r"><Delta value={r.change_pct} /></td>
          </tr>
        ))}</tbody>
      </table>
    </Card>
  )
}

export default function Diagnostics({ meta }) {
  const { view } = useView()
  const [sub, setSub] = useState('')
  const subs = meta.core_brands.find((b) => b.brand === view.brand)?.subcategories || []
  const state = useBrandApi('diagnostics', { subcategory: subs.includes(sub) ? sub : '' })
  if (view.mode === 'none') return <Note>Diagnostics compare two periods. Choose “Previous period” or “Same period last year” in Compare with.</Note>
  return (
    <>
      <div className="controls" style={{ marginBottom: 14 }}>
        <div className="control">
          <label>Scope</label>
          <select value={sub} onChange={(e) => setSub(e.target.value)}>
            <option value="">All of {view.brand}</option>
            {subs.map((s) => <option key={s} value={s}>{view.brand} · {s}</option>)}
          </select>
        </div>
      </div>
      <Async state={state}>
        {(d) => d.error ? <Note icon="⚠">{d.error}</Note> : (
          <>
            <Card>
              <div style={{ display: 'flex', gap: 14, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span className="kpi-value num" style={{ margin: 0 }}>{(d.change >= 0 ? '+' : '') + inr(d.change)}</span>
                <Delta value={d.change_pct} />
                <span className="muted">{inr(d.revenue_prev)} → {inr(d.revenue)}</span>
              </div>
              <p style={{ marginTop: 8 }}>{d.headline}</p>
            </Card>

            <div className="grid g2" style={{ marginTop: 14 }}>
              <Card title="Revenue bridge" sub="Exact split of the change: volume (units), mix (which SKUs) and price (discounts). Axis zoomed to show the steps.">
                <Waterfall d={d} />
              </Card>
              <Card title="What explains it" sub="Each candidate cause checked against the data. Supporting causes first.">
                {d.causes.map((c) => <Cause key={c.id} c={c} />)}
              </Card>
            </div>

            <Narrative brand={view.brand} diag={d} />

            <Section title="Where the change happened">
              <div className="grid g2">
                <Contributors title="SKUs" rows={d.contributors.sku} />
                <Contributors title="Retailers" rows={d.contributors.retailer} />
                <Contributors title="Regions" rows={d.contributors.region} />
                <Contributors title="Channels" rows={d.contributors.channel} />
              </div>
            </Section>
          </>
        )}
      </Async>
    </>
  )
}
