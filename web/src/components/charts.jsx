import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dateLabel, inr, inrAxis } from '../format'
import { TT, axis } from './ui'

/**
 * Current period vs comparison period on one axis. The comparison series is
 * aligned by position (bucket 1 vs bucket 1), so "same period last year" sits
 * directly under this year's line. Partial buckets get a hollow marker.
 */
export function TrendChart({ trend, fmt = inr, axisFmt = inrAxis, height = 260, curLabel = 'This period', prevLabel = 'Comparison' }) {
  const cur = trend.current || []
  const prev = trend.previous || []
  const data = cur.map((r, i) => ({
    bucket: r.bucket, cur: r.value, prev: prev[i]?.value ?? null, prevBucket: prev[i]?.bucket, partial: r.partial,
  }))
  const g = trend.grain
  return (
    <>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span><i className="sw line" style={{ background: 'var(--focus)' }} />{curLabel}</span>
        {prev.length > 0 && <span><i className="sw dash" />{prevLabel}</span>}
        {data.some((d) => d.partial) && <span className="faint">○ partial {g === 'M' ? 'month' : g === 'W' ? 'week' : 'day'}</span>}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => dateLabel(v, g)} {...axis} minTickGap={24} />
          <YAxis tickFormatter={(v) => axisFmt(v)} {...axis} width={64} />
          <Tooltip
            cursor={{ stroke: 'var(--text-3)', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload
              return (
                <TT
                  title={`${g === 'W' ? 'Week of ' : ''}${dateLabel(d.bucket, g === 'M' ? 'M' : 'D')}${d.partial ? ' (partial)' : ''}`}
                  rows={[
                    { label: curLabel, value: fmt(d.cur), color: 'var(--focus)' },
                    ...(d.prev != null ? [{ label: `${prevLabel} (${dateLabel(d.prevBucket, g === 'M' ? 'M' : 'D')})`, value: fmt(d.prev), color: 'var(--previous)', dashed: true }] : []),
                  ]}
                />
              )
            }}
          />
          <Line dataKey="prev" stroke="var(--previous)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls />
          <Line
            dataKey="cur" stroke="var(--focus)" strokeWidth={2} isAnimationActive={false}
            dot={(p) => (p.payload.partial ? <circle key={p.key} cx={p.cx} cy={p.cy} r={4} fill="var(--surface)" stroke="var(--focus)" strokeWidth={2} /> : <g key={p.key} />)}
            activeDot={{ r: 5, stroke: 'var(--surface)', strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </>
  )
}

/**
 * Horizontal bars, one per row, with the value and change printed beside each
 * bar (so colour never carries the meaning on its own).
 */
export function HBars({ rows, labelKey = 'name', valueKey = 'value', fmt = inr, color = 'var(--focus)', colorOf, height, extra, onClick }) {
  const h = height || Math.max(120, rows.length * 34 + 20)
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 90, bottom: 0, left: 0 }} barCategoryGap={8}>
        <XAxis type="number" hide domain={[0, 'dataMax']} />
        <YAxis type="category" dataKey={labelKey} width={140} {...axis} tick={{ fill: 'var(--text)', fontSize: 12 }} />
        <Tooltip
          cursor={{ fill: 'var(--surface-2)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const d = payload[0].payload
            return <TT title={d[labelKey]} rows={[{ label: 'Value', value: fmt(d[valueKey]) }, ...(extra ? extra(d) : [])]} />
          }}
        />
        <Bar
          dataKey={valueKey} radius={[0, 4, 4, 0]} isAnimationActive={false} onClick={onClick}
          label={{ position: 'right', formatter: (v) => fmt(v), fill: 'var(--text-2)', fontSize: 11 }}
        >
          {rows.map((r, i) => <Cell key={i} fill={colorOf ? colorOf(r) : color} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Bars that go left (negative) or right (positive) of zero. */
export function DivergingBars({ rows, labelKey = 'name', valueKey = 'value', fmt, height }) {
  const h = height || Math.max(120, rows.length * 32 + 20)
  const max = Math.max(1, ...rows.map((r) => Math.abs(r[valueKey] ?? 0)))
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 60, bottom: 0, left: 0 }} barCategoryGap={8}>
        <XAxis type="number" domain={[-max * 1.1, max * 1.1]} hide />
        <YAxis type="category" dataKey={labelKey} width={140} {...axis} tick={{ fill: 'var(--text)', fontSize: 12 }} />
        <ReferenceLine x={0} stroke="var(--text-3)" />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }}
          content={({ active, payload }) => active && payload?.length
            ? <TT title={payload[0].payload[labelKey]} rows={[{ label: 'Value', value: fmt(payload[0].payload[valueKey]) }]} /> : null} />
        <Bar dataKey={valueKey} radius={4} isAnimationActive={false}
          label={({ x, y, width, height, value }) => {
            if (value == null) return null
            const right = width >= 0 ? x + width : x   // bar's right edge (zero line for negative bars)
            return <text x={right + 6} y={y + height / 2 + 4} fontSize={11} fill="var(--text-2)">{fmt(value)}</text>
          }}>
          {rows.map((r, i) => <Cell key={i} fill={(r[valueKey] ?? 0) >= 0 ? 'var(--focus)' : 'var(--external)'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
