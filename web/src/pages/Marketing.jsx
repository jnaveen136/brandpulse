import { DivergingBars, TrendChart } from '../components/charts'
import { Async, Card, KpiCard, Note, Section } from '../components/ui'
import { inr, num, pct, signed } from '../format'
import { useBrandApi, useView } from '../state'

export default function Marketing() {
  const state = useBrandApi('marketing')
  const { view } = useView()
  return (
    <Async state={state}>
      {(d) => (
        <>
          <Section title={`${view.brand} promotions`} sub="Promotions run in two seasons: Summer (Mar–May, 10% off) and Festive (Sep–Nov, 15% off).">
            <div className="grid g4">{d.promo_kpis.map((k) => <KpiCard key={k.kpi} k={k} />)}</div>
            <div className="grid g2" style={{ marginTop: 14 }}>
              <Card title="Promo share of revenue over time" sub="Zero outside the promo seasons">
                <TrendChart trend={d.promo_trend} fmt={(v) => pct(v)} axisFmt={(v) => `${Math.round(v)}%`} prevLabel={d.comparison?.label || 'Comparison'} height={220} />
              </Card>
              <Card title="Promo vs non-promo, inside promo months" sub="Per transaction. Shows whether the discount pays for itself.">
                <div className="tbl-wrap">
                  <table>
                    <thead><tr><th>Promotion</th><th className="r">Transactions</th><th className="r">Units / txn</th><th className="r">Revenue / txn</th><th className="r">Discount</th><th className="r">Revenue</th></tr></thead>
                    <tbody>{d.promo_by_type.map((r) => (
                      <tr key={r.Promotion}>
                        <td style={{ fontWeight: 600 }}>{r.Promotion === 'None' ? 'No promotion' : r.Promotion}</td>
                        <td className="r num">{num(r.transactions)}</td><td className="r num">{r.units_per_txn?.toFixed(1)}</td>
                        <td className="r num">{inr(r.revenue_per_txn)}</td><td className="r num">{pct(r.discount_pct)}</td><td className="r num">{inr(r.revenue)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                {d.promo_by_type.length === 0 && <p className="muted">No promo-season transactions in this period.</p>}
              </Card>
            </div>
            <div style={{ marginTop: 14 }}>
              <Card title="Promotion response by retailer" sub="Revenue per promo transaction vs non-promo transactions in the same months">
                <DivergingBars rows={d.promo_by_retailer.map((r) => ({ name: r.Retailer, value: r.value }))} fmt={(v) => signed(v)} />
              </Card>
            </div>
          </Section>

          <Section title="Company campaigns" sub={d.company.note}>
            <div style={{ marginBottom: 12 }}><Note icon="⚠">{d.company.note}</Note></div>
            <div className="grid g3">{d.company.kpis.map((k) => <KpiCard key={k.kpi} k={k} />)}</div>
            <div className="grid g2" style={{ marginTop: 14 }}>
              <Card title="Campaign spend over time"><TrendChart trend={d.company.spend_trend} prevLabel={d.comparison?.label || 'Comparison'} height={220} /></Card>
              <Card title="By campaign and marketing channel">
                <div className="tbl-wrap">
                  <table>
                    <thead><tr><th>Campaign</th><th>Channel</th><th className="r">Spend</th><th className="r">ROI</th><th className="r">Conversion</th></tr></thead>
                    <tbody>{[...d.company.campaigns].sort((a, b) => b.spend - a.spend).map((r) => (
                      <tr key={r.Campaign + r.Channel}>
                        <td>{r.Campaign}</td><td className="muted">{r.Channel}</td><td className="r num">{inr(r.spend)}</td>
                        <td className="r num">{r.roi?.toFixed(2)}×</td><td className="r num">{pct(r.conversion_pct, 2)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
            </div>
          </Section>
        </>
      )}
    </Async>
  )
}
