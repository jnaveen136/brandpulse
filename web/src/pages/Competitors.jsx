import { CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { DivergingBars, HBars } from '../components/charts'
import { Async, Card, Delta, Note, Section, TT, axis } from '../components/ui'
import { dateLabel, inr, longDate, pct, pp, signed } from '../format'
import { useBrandApi, useView } from '../state'

const DASHES = ['', '6 4', '2 3', '8 3 2 3']

function Tile({ label, value, delta, deltaKind = 'pp', higherIsBetter = true, sub }) {
  return (
    <div className="card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value num">{value}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        {delta !== undefined && <Delta value={delta} kind={deltaKind} higherIsBetter={higherIsBetter} />}
        {sub && <span className="kpi-prev">{sub}</span>}
      </div>
    </div>
  )
}

function Answer({ q, a, why, children }) {
  return (
    <Card>
      <div className="answer">
        <span className="q">{q}</span>
        <span className="a">{a}</span>
        {why && <span className="why">{why}</span>}
        {children}
      </div>
    </Card>
  )
}

function MarketShare({ ms, series, brand }) {
  if (!series.length) return <Note>No market-share data for {brand} or its rivals in this period.</Note>
  const brands = [...new Set(series.map((r) => r.Brand))]
  const rivals = brands.filter((b) => b !== brand)
  const byDate = {}
  series.forEach((r) => { (byDate[r.Date] ||= { Date: r.Date })[r.Brand] = r.MarketSharePct })
  const data = Object.values(byDate).sort((a, b) => a.Date.localeCompare(b.Date))
  const last = data[data.length - 1]
  return (
    <>
      <div className="legend" style={{ marginBottom: 6 }}>
        {ms.available && <span><i className="sw line" style={{ background: 'var(--focus)' }} />{brand}</span>}
        {rivals.map((b, i) => (
          <span key={b}><svg width="18" height="4"><line x1="0" y1="2" x2="18" y2="2" stroke="var(--external)" strokeWidth="2" strokeDasharray={DASHES[i % 4]} /></svg>{b}</span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 6, right: 80, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="Date" tickFormatter={(v) => dateLabel(v, 'M')} {...axis} minTickGap={20} />
          <YAxis {...axis} tickFormatter={(v) => `${v}%`} width={44} domain={['auto', 'auto']} />
          <Tooltip cursor={{ stroke: 'var(--text-3)', strokeDasharray: '3 3' }} content={({ active, payload }) => active && payload?.length
            ? <TT title={dateLabel(payload[0].payload.Date, 'M')} rows={payload.map((p) => ({ label: p.dataKey, value: pct(p.value, 2), color: p.stroke }))} /> : null} />
          {ms.available && <Line dataKey={brand} stroke="var(--focus)" strokeWidth={2.5} dot={false} isAnimationActive={false}
            label={(p) => p.index === data.length - 1 ? <text x={p.x + 6} y={p.y + 4} fontSize={11} fill="var(--text)">{brand}</text> : null} />}
          {rivals.map((b, i) => (
            <Line key={b} dataKey={b} stroke="var(--external)" strokeWidth={2} strokeDasharray={DASHES[i % 4]} dot={false} isAnimationActive={false}
              label={(p) => p.index === data.length - 1 ? <text x={p.x + 6} y={p.y + 4} fontSize={11} fill="var(--text-2)">{b}</text> : null} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {last && <p className="faint small">Latest month: {Object.entries(last).filter(([k]) => k !== 'Date').map(([k, v]) => `${k} ${pct(v, 1)}`).join(' · ')}</p>}
    </>
  )
}

const EVENT_SHAPE = { 'Price Cut': 'triangle', 'New Launch': 'star', 'TV Campaign': 'circle' }

function Activity({ act }) {
  const data = act.events.map((e) => ({ ...e, t: new Date(e.date).getTime() }))
  const groups = Object.keys(EVENT_SHAPE).map((ev) => ({ ev, rows: data.filter((d) => d.event === ev) }))
  return (
    <>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span>▲ Price cut</span><span>★ New launch</span><span>● TV campaign</span>
      </div>
      {data.length === 0 ? <p className="muted">No competitor events in this period.</p> : (
        <ResponsiveContainer width="100%" height={70 + act.manufacturers.length * 40}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis type="number" dataKey="t" domain={['dataMin - 864000000', 'dataMax + 864000000']} {...axis}
              tickFormatter={(v) => dateLabel(new Date(v).toISOString(), 'D')} />
            <YAxis type="category" dataKey="competitor" allowDuplicatedCategory={false} {...axis} width={80} tick={{ fill: 'var(--text)', fontSize: 12 }} />
            <ZAxis range={[90, 90]} />
            <Tooltip cursor={false} content={({ active, payload }) => active && payload?.length
              ? <TT title={`${payload[0].payload.competitor} · ${payload[0].payload.event}`}
                rows={[{ label: 'Date', value: longDate(payload[0].payload.date) }, { label: 'Price impact', value: signed(payload[0].payload.price_impact_pct, 0) }]} /> : null} />
            {groups.map((g) => <Scatter key={g.ev} data={g.rows} shape={EVENT_SHAPE[g.ev]} fill="var(--text-2)" isAnimationActive={false} />)}
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </>
  )
}

export default function Competitors() {
  const state = useBrandApi('competitors')
  const { view } = useView()
  return (
    <Async state={state}>
      {(d) => {
        const pp_ = d.price_position
        const ms = d.market_share
        const closestShare = ms.rivals[0]
        const disc = d.answers.who_is_discounting
        const gained = d.answers.who_gained_share.subcategory_share
        const launched = d.answers.who_launched
        const topDisc = disc.rivals[0]
        return (
          <>
            <div className="grid g5">
              <Tile label="Price gap vs rivals" value={signed(pp_.price_gap_pct)} delta={pp_.price_gap_pct != null && pp_.price_gap_pct_prev != null ? pp_.price_gap_pct - pp_.price_gap_pct_prev : null}
                sub="our ASP vs rivals, same sub-category" higherIsBetter={null} />
              <Tile label="Our discount" value={pct(pp_.our_discount_pct, 2)} delta={pp_.discount_gap_pp} sub="gap vs rivals" higherIsBetter={null} />
              <Tile label="Competitor discount" value={pct(pp_.competitor_discount_pct, 2)}
                delta={pp_.competitor_discount_pct != null && pp_.competitor_discount_pct_prev != null ? pp_.competitor_discount_pct - pp_.competitor_discount_pct_prev : null}
                higherIsBetter={false} sub="vs comparison" />
              {ms.available
                ? <Tile label="Market share" value={pct(ms.our_share, 2)} delta={ms.our_change_pp} sub={closestShare ? `gap vs ${closestShare.brand}: ${pp(closestShare.gap_pp)}` : ''} />
                : <Tile label="Market share" value="n/a" sub="no data for this brand" />}
              <Tile label="Competitor activity index" value={d.activity.index?.toFixed(1) ?? '—'} delta={d.activity.change_pct} deltaKind="pct" higherIsBetter={false}
                sub={`${d.activity.manufacturers.join(' & ')} events / 30 days`} />
            </div>

            <Section title="Answers" sub={`For ${view.brand}'s competitive set: the external brands in its sub-categories only.`}>
              <div className="grid g3">
                <Answer q="Who is discounting?" a={topDisc ? `${topDisc.brand}, ${pct(topDisc.discount_pct, 2)}` : '—'}
                  why={`Average discount in the sub-categories where they meet ${view.brand}. ${view.brand}: ${pct(disc.ours, 2)}.`}>
                  <table><tbody>{disc.rivals.map((r) => (
                    <tr key={r.brand}><td>{r.brand}</td><td className="r num">{pct(r.discount_pct, 2)}</td><td className="r"><Delta value={r.change_pp} kind="pp" higherIsBetter={false} /></td></tr>
                  ))}</tbody></table>
                </Answer>
                <Answer q="Which competitor gained share?" a={gained[0] ? `${gained[0].Brand}, ${pp(gained[0].change_pp)}` : '—'}
                  why="Change in share of sub-category revenue (11 tracked brands), weighted across shared sub-categories.">
                  <table><tbody>{gained.map((r) => (
                    <tr key={r.Brand}><td>{r.Brand}</td><td className="faint small">{r.subcategories.join(', ')}</td><td className="r"><Delta value={r.change_pp} kind="pp" /></td></tr>
                  ))}</tbody></table>
                  {d.answers.who_gained_share.market_share.length > 0 && (
                    <p className="small muted">Reported market share: {d.answers.who_gained_share.market_share.map((r) => `${r.brand} ${pp(r.change_pp, 2)}`).join(', ')}</p>
                  )}
                </Answer>
                <Answer q="Which competitor launched a product?"
                  a={launched.launches.length ? [...new Set(launched.launches.map((e) => e.competitor))].join(' & ') : 'No launches'}
                  why={`${launched.launches.length} launch${launched.launches.length === 1 ? '' : 'es'} and ${launched.price_cuts.length} price cut${launched.price_cuts.length === 1 ? '' : 's'} in this period. ${launched.note}`}>
                  <table><tbody>{launched.launches.map((e, i) => (
                    <tr key={i}><td>{e.competitor}</td><td className="r muted">{longDate(e.date)}</td></tr>
                  ))}</tbody></table>
                </Answer>
              </div>
            </Section>

            <Section title="Price position" sub="Our average selling price vs external rivals in each sub-category we sell in.">
              <div className="grid g2">
                <Card title="Price gap by sub-category" sub="Negative = we are cheaper than rivals">
                  <DivergingBars rows={pp_.by_subcategory.map((r) => ({ name: r.SubCategory, value: r.price_gap_pct }))} fmt={(v) => signed(v)} />
                  <div className="tbl-wrap">
                    <table>
                      <thead><tr><th>Sub-category</th><th className="r">Our ASP</th><th className="r">Rival ASP</th><th className="r">Our disc.</th><th className="r">Rival disc.</th><th>Rivals</th></tr></thead>
                      <tbody>{pp_.by_subcategory.map((r) => (
                        <tr key={r.SubCategory}>
                          <td>{r.SubCategory}</td><td className="r num">₹{r.our_asp?.toFixed(1)}</td><td className="r num">₹{r.rival_asp?.toFixed(1)}</td>
                          <td className="r num">{pct(r.our_discount_pct, 2)}</td><td className="r num">{pct(r.rival_discount_pct, 2)}</td>
                          <td className="muted small">{r.rivals.join(', ')}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                </Card>
                <Card title="ASP over time" sub="Monthly, ours vs rivals in the same sub-category">
                  <div className="legend" style={{ marginBottom: 6 }}>
                    <span><i className="sw line" style={{ background: 'var(--focus)' }} />{view.brand}</span>
                    <span><i className="sw line" style={{ background: 'var(--external)' }} />External rivals</span>
                  </div>
                  <div className="grid g2">
                    {d.price_trend.map((t) => (
                      <div key={t.SubCategory}>
                        <div className="small" style={{ fontWeight: 600 }}>{t.SubCategory}</div>
                        <ResponsiveContainer width="100%" height={130}>
                          <LineChart data={t.series} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
                            <CartesianGrid stroke="var(--grid)" vertical={false} />
                            <XAxis dataKey="bucket" tickFormatter={(v) => dateLabel(v, 'M')} {...axis} minTickGap={20} />
                            <YAxis {...axis} width={40} domain={['auto', 'auto']} tickFormatter={(v) => `₹${Math.round(v)}`} />
                            <Tooltip content={({ active, payload }) => active && payload?.length
                              ? <TT title={dateLabel(payload[0].payload.bucket, 'M')} rows={[
                                { label: view.brand, value: `₹${payload[0].payload.ours?.toFixed(1)}`, color: 'var(--focus)' },
                                { label: 'Rivals', value: `₹${payload[0].payload.rivals?.toFixed(1)}`, color: 'var(--external)' }]} /> : null} />
                            <Line dataKey="ours" stroke="var(--focus)" strokeWidth={2} dot={false} isAnimationActive={false} />
                            <Line dataKey="rivals" stroke="var(--external)" strokeWidth={2} dot={false} isAnimationActive={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </Section>

            <Section title="Share" sub="Reported market share (6 brands only) and share of sub-category revenue (all tracked brands).">
              <div className="grid g2">
                <Card title="Market share" sub={ms.note}>
                  <MarketShare ms={ms} series={d.market_share_series} brand={view.brand} />
                </Card>
                <Card title="Share of sub-category revenue" sub="Among the 11 tracked brands. Hover for the change.">
                  <div className="grid g2">
                    {[...new Set(d.subcategory_share.map((r) => r.SubCategory))].map((sc) => {
                      const rows = d.subcategory_share.filter((r) => r.SubCategory === sc)
                        .sort((a, b) => (b.share_pct ?? 0) - (a.share_pct ?? 0))
                        .map((r) => ({ name: r.Brand, value: r.share_pct, chg: r.change_pp, focus: r.is_focus }))
                      return (
                        <div key={sc}>
                          <div className="small" style={{ fontWeight: 600 }}>{sc}</div>
                          <HBars rows={rows} fmt={(v) => pct(v)} colorOf={(r) => (r.focus ? 'var(--focus)' : 'var(--external)')}
                            extra={(r) => [{ label: 'Change', value: pp(r.chg) }]} height={rows.length * 26 + 10} />
                        </div>
                      )
                    })}
                  </div>
                </Card>
              </div>
            </Section>

            <Section title="Competitor activity" sub={d.activity.note}>
              <Card title={`Events by ${d.activity.manufacturers.join(' and ')}`}
                sub={`Activity index ${d.activity.index?.toFixed(1)} vs ${d.activity.index_prev?.toFixed(1) ?? '—'} (price cut = 3, launch = 2, TV = 1, scaled by price impact, per 30 days)`}>
                <Activity act={d.activity} />
              </Card>
            </Section>
          </>
        )
      }}
    </Async>
  )
}
