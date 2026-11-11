import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { DivergingBars, HBars } from '../components/charts'
import { Async, Card, Delta, Note, Section } from '../components/ui'
import { inr, pct, signed } from '../format'
import { useBrandApi, useView } from '../state'

const tierColor = (t) => (t === 'Tier1' ? 'var(--focus)' : 'var(--sibling)')

function Spark({ rows }) {
  return (
    <ResponsiveContainer width={110} height={28}>
      <LineChart data={rows}><Line dataKey="value" stroke="var(--focus)" strokeWidth={1.5} dot={false} isAnimationActive={false} /></LineChart>
    </ResponsiveContainer>
  )
}

export default function Retailers() {
  const state = useBrandApi('retailers')
  const { view } = useView()
  return (
    <Async state={state}>
      {(d) => {
        const t = d.table
        const trend = {}
        d.trend.current.forEach((r) => (trend[r.Retailer] ||= []).push(r))
        const fmtA = (a) => (a.format === 'currency' ? inr(a.value) : a.question.includes('growing') ? signed(a.value) : pct(a.value))
        return (
          <>
            <div className="grid g4">
              {d.answers.map((a) => (
                <Card key={a.question}>
                  <div className="answer"><span className="q">{a.question}</span><span className="a">{a.retailer}</span><span className="why num">{fmtA(a)}</span></div>
                </Card>
              ))}
            </div>

            <Section title={`Revenue and margin by retailer`} sub={`${view.brand} only. Tier-1 retailers in blue, Tier-2 in grey.`}>
              <div className="grid g2">
                <Card title="Revenue" right={<div className="legend"><span><i className="sw" style={{ background: 'var(--focus)' }} />Tier 1</span><span><i className="sw" style={{ background: 'var(--sibling)' }} />Tier 2</span></div>}>
                  <HBars rows={t.map((r) => ({ name: r.Retailer, value: r.revenue, tier: r.Tier, chg: r.revenue_delta_pct }))}
                    colorOf={(r) => tierColor(r.tier)} extra={(r) => [{ label: 'Change', value: signed(r.chg) }, { label: 'Tier', value: r.tier }]} />
                </Card>
                <Card title="Margin %">
                  <HBars rows={[...t].sort((a, b) => b.margin_pct - a.margin_pct).map((r) => ({ name: r.Retailer, value: r.margin_pct, tier: r.Tier, m: r.margin }))}
                    fmt={(v) => pct(v)} colorOf={(r) => tierColor(r.tier)} extra={(r) => [{ label: 'Margin', value: inr(r.m) }]} />
                </Card>
              </div>
            </Section>

            <Section title="Pricing and promotion response by retailer">
              <div className="grid g2">
                <Card title="Retailer price index" sub={`${d.notes.price_index} Bars show the difference from 100.`}>
                  <DivergingBars rows={[...t].sort((a, b) => b.price_index - a.price_index).map((r) => ({ name: r.Retailer, value: r.price_index == null ? null : r.price_index - 100 }))}
                    fmt={(v) => (v == null ? '—' : (100 + v).toFixed(1))} />
                </Card>
                <Card title="Promotion effectiveness" sub={`Revenue per promo transaction vs non-promo, same months. ${d.notes.promo_lift}`}>
                  <DivergingBars rows={[...t].sort((a, b) => (b.promo_revenue_lift_pct ?? -999) - (a.promo_revenue_lift_pct ?? -999)).map((r) => ({ name: r.Retailer, value: r.promo_revenue_lift_pct }))}
                    fmt={(v) => signed(v)} />
                </Card>
              </div>
            </Section>

            <Section title="Retailer scorecard" sub="Growth vs the comparison period, with the period's trend.">
              <Card>
                <div className="tbl-wrap">
                  <table>
                    <thead><tr>
                      <th>Retailer</th><th>Channel</th><th>Tier</th><th className="r">Revenue</th><th className="r">Share</th><th className="r">Growth</th>
                      <th className="r">Margin %</th><th className="r">ASP</th><th className="r">Price idx</th><th className="r">Promo share</th><th className="r">Unit lift</th><th>Trend</th>
                    </tr></thead>
                    <tbody>{t.map((r) => (
                      <tr key={r.Retailer}>
                        <td style={{ fontWeight: 600 }}>{r.Retailer}</td><td className="muted">{r.Channel}</td><td className="muted">{r.Tier}</td>
                        <td className="r num">{inr(r.revenue)}</td><td className="r num">{pct(r.revenue_share_pct)}</td>
                        <td className="r"><Delta value={r.revenue_delta_pct} /></td>
                        <td className="r num">{pct(r.margin_pct)}</td><td className="r num">₹{r.asp?.toFixed(1)}</td>
                        <td className="r num">{r.price_index?.toFixed(1)}</td><td className="r num">{pct(r.promo_revenue_share)}</td>
                        <td className="r num">{signed(r.promo_lift_pct)}</td>
                        <td>{trend[r.Retailer] && <Spark rows={trend[r.Retailer]} />}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
            </Section>

            <Section title="Top SKUs by retailer" sub="Our three best-selling variants at each retailer in this period.">
              <div className="grid g5">
                {Object.entries(d.top_skus).map(([ret, rows]) => (
                  <Card key={ret} title={ret}>
                    {rows.map((s, i) => (
                      <div key={s.ProductID} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '3px 0', fontSize: '0.82rem' }}>
                        <span><span className="faint">{i + 1}.</span> {s.ProductName.replace(`${view.brand} `, '')} <span className="faint small">{s.SubCategory}</span></span>
                        <span className="num">{inr(s.value)}</span>
                      </div>
                    ))}
                  </Card>
                ))}
              </div>
            </Section>

            <Section title="By tier and channel">
              <div className="grid g2">
                {[['Tier', d.by_tier], ['Channel', d.by_channel]].map(([dim, rows]) => (
                  <Card key={dim} title={`Revenue by ${dim.toLowerCase()}`}>
                    <table><tbody>{rows.map((r) => (
                      <tr key={r[dim]}><td>{r[dim]}</td><td className="r num">{inr(r.current)}</td><td className="r"><Delta value={r.delta_pct} /></td></tr>
                    ))}</tbody></table>
                  </Card>
                ))}
              </div>
              <div style={{ marginTop: 12 }}><Note>Retailer names and channels come from the dataset as given (synthetic data, ₹ prices for global chains).</Note></div>
            </Section>
          </>
        )
      }}
    </Async>
  )
}
