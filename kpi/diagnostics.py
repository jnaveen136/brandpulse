"""Diagnostic analytics: why did a core brand's revenue change?

For a brand (optionally one SubCategory or SKU) and a period vs. its
comparison period, this module:

1. Splits the revenue change into an exact bridge
       ΔRevenue = Volume effect + Mix effect + Price effect
   computed SKU by SKU:
       Price  = Σ_i U1_i × (P1_i − P0_i)         same units, new vs old price
       Volume = (U1 − U0) × ASP0                 more/fewer units at the old average price
       Mix    = Σ_i U1_i × P0_i − U1 × ASP0      shift between cheaper and dearer SKUs
   MRP never changes in this data, so the price effect is entirely discount-driven.

2. Finds where the change happened: SKUs, retailers, regions and channels
   ranked by their contribution.

3. Checks a fixed list of candidate causes against the data, each with the
   evidence numbers:
       promotions started / ended / changed depth
       competitors discounting more in our SubCategories
       competitor events in the window (price cuts, launches, campaigns)
       rivals gaining share of our SubCategories
       stock-out risk up
       rating down / leakage complaints
   A cause is "supporting" when its direction is consistent with the
   revenue move, otherwise "not a factor".

Everything is deterministic. The LLM layer only narrates this output.
"""
from __future__ import annotations

import pandas as pd

from .competitive import Competitive
from .engine import Engine, PeriodLike, _clean
from .filters import Filters


def _r(x, n=2):
    x = _clean(x)
    return None if x is None else round(x, n)


class Diagnostics:
    def __init__(self, engine: Engine, competitive: Competitive | None = None):
        self.e = engine
        self.c = competitive or Competitive(engine)

    def _sku_frame(self, f: Filters, period) -> pd.DataFrame:
        df, _ = self.e.frame("sales", f, period)
        g = df.groupby("ProductID").agg(Revenue=("Revenue", "sum"), Units=("UnitsSold", "sum"))
        g["Price"] = g["Revenue"] / g["Units"]
        return g

    def _promo_stats(self, f: Filters, period) -> dict:
        df, _ = self.e.frame("sales", f, period)
        promo, base = df[df["HasPromo"]], df[~df["HasPromo"] & df["InPromoSeason"]]
        return {"promo_txns": int(len(promo)), "base_txns": int(len(base)), "units": float(df["UnitsSold"].sum()),
                "promo_upt": float(promo["UnitsSold"].mean()) if len(promo) else 0.0,
                "base_upt": float(base["UnitsSold"].mean()) if len(base) else 0.0}

    def bridge(self, f: Filters, cur, prev) -> dict:
        a, b = self._sku_frame(f, cur), self._sku_frame(f, prev)
        j = a.add_suffix("1").join(b.add_suffix("0"), how="outer").fillna({"Revenue1": 0, "Units1": 0, "Revenue0": 0, "Units0": 0})
        both = j.dropna(subset=["Price1", "Price0"])
        price = float((both["Units1"] * (both["Price1"] - both["Price0"])).sum())
        u1, u0 = j["Units1"].sum(), j["Units0"].sum()
        asp0 = j["Revenue0"].sum() / u0 if u0 else 0.0
        volume = float((u1 - u0) * asp0)
        p0 = j["Price0"].fillna(j["Price1"])  # SKUs new in the current period: valued at their own price
        mix = float((j["Units1"] * p0).sum() - u1 * asp0)
        total = float(j["Revenue1"].sum() - j["Revenue0"].sum())
        return {"revenue": float(j["Revenue1"].sum()), "revenue_prev": float(j["Revenue0"].sum()), "change": total,
                "volume": volume, "mix": mix, "price": price, "residual": total - volume - mix - price}

    def _contributors(self, dim: str, f: Filters, period, mode, as_of, top: int = 5) -> list[dict]:
        b = self.e.breakdown_compare("revenue", dim, f, period, mode, as_of)
        b = b.assign(abs_delta=b["delta"].abs()).sort_values("abs_delta", ascending=False).head(top)
        if dim == "ProductID":
            names = self.e.m.products.set_index("ProductID")["ProductName"]
            b["name"] = b["ProductID"].map(names)
        else:
            b["name"] = b[dim]
        return [{"name": r["name"], "revenue": _r(r["current"]), "revenue_prev": _r(r["previous"]),
                 "change": _r(r["delta"]), "change_pct": _r(r["delta_pct"])} for _, r in b.iterrows()]

    def explain(self, brand: str, period: PeriodLike = "MTD", mode: str = "yoy", as_of=None,
                subcategory: str | None = None, product: str | None = None, base: Filters | None = None) -> dict:
        f = (base or Filters()).with_(**{k: v for k, v in
                                         {"brands": brand, "subcategories": subcategory, "products": product}.items() if v})
        p, preset = self.e.period(period, as_of)
        c = self.e.comparison_period(period, mode, as_of)
        if c is None or c.coverage(self.e.data_start, self.e.data_end) < 1:
            return {"error": "The comparison period is not fully covered by the data; pick a later period or another comparison."}

        br = self.bridge(f, p, c)
        direction = "down" if br["change"] < 0 else "up"
        sign = -1 if direction == "down" else 1
        def kc(kpi, ff=f):  # current, previous and change of a KPI over the two resolved periods
            cur = self.e.value(kpi, ff, p)
            prv = self.e.value(kpi, ff, c)
            return cur, prv, (None if cur is None or prv is None else cur - prv)

        causes = []

        def add(cid, title, effect_sign, evidence, text, impact=None):
            """effect_sign: +1 if this cause pushes revenue up, -1 if down, 0 if neutral."""
            supporting = effect_sign != 0 and effect_sign == sign
            share = None if impact is None or not br["change"] else abs(impact) / abs(br["change"])
            if share is not None and share < 0.10:  # quantified but too small to matter
                supporting = False
            causes.append({"id": cid, "title": title, "supporting": supporting, "effect": effect_sign,
                           "impact": _r(impact), "share_of_change": _r(share, 3), "evidence": evidence, "text": text})

        # 1. Promotions
        ps_cur, ps_prev, ps_d = kc("promo_revenue_share")
        dc_cur, dc_prev, dc_d = kc("discount_pct")
        lift = self.e.value("promo_revenue_lift_pct", f, p)
        if ps_prev is not None and ps_cur is not None:
            if ps_prev > 1 and ps_cur < 1:
                state = "ended"
            elif ps_prev < 1 and ps_cur > 1:
                state = "started"
            else:
                state = "changed" if abs(ps_d) >= 2 else "unchanged"
            # A promotion moves revenue two ways: the discount (the bridge's price effect) and the
            # extra units each promo transaction sells. Net promo impact = price effect + promo volume,
            # where promo volume = change in promo transactions x extra units per promo txn x old ASP.
            st1, st0 = self._promo_stats(f, p), self._promo_stats(f, c)
            ref = st1 if st1["promo_txns"] else st0
            extra_upt = (ref["promo_upt"] - ref["base_upt"]) if ref["promo_txns"] and ref["base_txns"] else 0.0
            asp0 = br["revenue_prev"] / st0["units"] if st0["units"] else 0.0
            promo_volume = (st1["promo_txns"] - st0["promo_txns"]) * extra_upt * asp0
            net = br["price"] + promo_volume
            eff = 0 if state == "unchanged" or abs(net) < 1 else (1 if net > 0 else -1)
            add("promotions", f"Promotions {state}", eff,
                {"promo_revenue_share_pct": _r(ps_cur), "promo_revenue_share_pct_prev": _r(ps_prev),
                 "discount_pct": _r(dc_cur), "discount_pct_prev": _r(dc_prev),
                 "promo_transactions": st1["promo_txns"], "promo_transactions_prev": st0["promo_txns"],
                 "extra_units_per_promo_txn": _r(extra_upt), "promo_revenue_lift_per_txn_pct": _r(lift),
                 "discount_effect": _r(br["price"]), "promo_volume_effect": _r(promo_volume), "net_effect": _r(net)},
                f"Promo share of revenue went from {ps_prev:.1f}% to {ps_cur:.1f}% (average discount {(dc_prev or 0):.1f}% → "
                f"{(dc_cur or 0):.1f}%). Discount effect {br['price']:+,.0f}, promo volume effect {promo_volume:+,.0f}, "
                f"net {net:+,.0f}.",
                impact=net)

        # 2. Competitor discounting in our SubCategories
        pos = self.c.price_position(brand, period, mode, as_of, base=base)
        cd, cdp = pos["competitor_discount_pct"], pos["competitor_discount_pct_prev"]
        if cd is not None and cdp is not None:
            d = cd - cdp
            add("competitor_discounting", "Competitors discounting " + ("more" if d > 0.2 else "less" if d < -0.2 else "about the same"),
                -1 if d > 0.2 else (1 if d < -0.2 else 0),
                {"competitor_discount_pct": _r(cd), "competitor_discount_pct_prev": _r(cdp), "change_pp": _r(d),
                 "our_discount_pct": _r(pos["our_discount_pct"])},
                f"External rivals in our SubCategories averaged a {cd:.1f}% discount vs {cdp:.1f}% before ({d:+.1f}pp).")

        # 3. Competitor events in the window
        act = self.c.activity(brand, period, mode, as_of, base=base)
        cuts = [e for e in act["events"] if e["event"] == "Price Cut"]
        launches = [e for e in act["events"] if e["event"] == "New Launch"]
        ch = act["change_pct"]
        if act["events"] or (act["index_prev"] or 0) > 0:
            tv = len(act["events"]) - len(cuts) - len(launches)
            add("competitor_events", f"{len(act['events'])} competitor events ({len(cuts)} price cuts, {len(launches)} launches, {tv} TV campaigns)",
                -1 if (ch is not None and ch > 20) or cuts else 0,
                {"activity_index": _r(act["index"]), "activity_index_prev": _r(act["index_prev"]),
                 "events": act["events"][:10], "manufacturers": act["manufacturers"]},
                f"Competitor Activity Index {(act['index'] or 0):.1f} vs {(act['index_prev'] or 0):.1f} before. "
                + (f"Price cuts: {', '.join(e['competitor'] + ' ' + e['date'] for e in cuts)}. " if cuts else "")
                + (f"Launches: {', '.join(e['competitor'] + ' ' + e['date'] for e in launches)}." if launches else ""))

        # 4. Rivals gaining share of our SubCategories
        sh = self.c.subcategory_share(brand, period, mode, as_of, base=base)
        if subcategory:
            sh = sh[sh["SubCategory"] == subcategory]
        ours = sh[sh["is_focus"]]
        rivals = sh[~sh["is_focus"]].dropna(subset=["change_pp"]).sort_values("change_pp", ascending=False)
        if not ours.empty and ours["change_pp"].notna().any():
            our_d = float((ours["change_pp"] * ours["revenue"].fillna(0)).sum() / max(ours["revenue"].fillna(0).sum(), 1e-9))
            top = rivals.head(3)
            add("share_shift", "Lost share of SubCategory to rivals" if our_d < -0.5 else
                ("Gained share of SubCategory" if our_d > 0.5 else "Share of SubCategory stable"),
                -1 if our_d < -0.5 else (1 if our_d > 0.5 else 0),
                {"our_change_pp": _r(our_d), "by_subcategory": ours[["SubCategory", "share_pct", "share_pct_prev", "change_pp"]].round(2).to_dict("records"),
                 "top_gainers": top[["SubCategory", "Brand", "share_pct", "change_pp", "revenue_growth_pct"]].round(2).to_dict("records")},
                f"Our share of SubCategory revenue (tracked brands) moved {our_d:+.1f}pp. Biggest rival gains: "
                + ", ".join(f"{r.Brand} in {r.SubCategory} ({r.change_pp:+.1f}pp)" for r in top.itertuples()) + ".")

        # 5. Stock-outs
        so_cur, so_prev, so_d = kc("stockout_risk_pct")
        if so_d is not None:
            add("stockouts", "Stock-out risk " + ("up" if so_d > 1 else "down" if so_d < -1 else "unchanged"),
                -1 if so_d > 1 else (1 if so_d < -1 else 0),
                {"stockout_risk_pct": _r(so_cur), "stockout_risk_pct_prev": _r(so_prev)},
                f"Share of stock snapshots below reorder level: {so_cur:.1f}% vs {so_prev:.1f}%.")

        # 6. Quality / ratings
        rt_cur, rt_prev, rt_d = kc("avg_rating")
        lk_cur, lk_prev, lk_d = kc("leakage_complaint_pct")
        if rt_d is not None:
            bad = (rt_d < -0.1) or ((lk_d or 0) > 2)
            good = rt_d > 0.1
            add("quality", "Customer ratings " + ("worsened" if bad else "improved" if good else "stable"),
                -1 if bad else (1 if good else 0),
                {"avg_rating": _r(rt_cur), "avg_rating_prev": _r(rt_prev),
                 "leakage_complaint_pct": _r(lk_cur), "leakage_complaint_pct_prev": _r(lk_prev)},
                f"Average rating {rt_cur:.2f} vs {rt_prev:.2f}; leakage complaints {(lk_cur or 0):.1f}% of reviews vs {(lk_prev or 0):.1f}%.")

        # Rank: supporting causes first, then by size of quantified impact / evidence
        causes.sort(key=lambda x: (not x["supporting"], x["impact"] is None, -abs(x["impact"] or 0)))

        bridge_items = [
            {"name": "Volume", "value": _r(br["volume"]),
             "text": "More units" if br["volume"] > 0 else "Fewer units"},
            {"name": "Mix", "value": _r(br["mix"]),
             "text": "Sales shifted to higher-priced SKUs" if br["mix"] > 0 else "Sales shifted to lower-priced SKUs"},
            {"name": "Price / discount", "value": _r(br["price"]),
             "text": "Lower discounts" if br["price"] > 0 else "Deeper discounts"},
        ]
        main = max(bridge_items, key=lambda x: abs(x["value"] or 0))
        top_sku = self._contributors("ProductID", f, period, mode, as_of, 1)
        headline = (f"{brand}{' ' + subcategory if subcategory else ''} revenue {direction} "
                    f"{abs(br['change']):,.0f} ({100 * br['change'] / br['revenue_prev']:+.1f}%) "
                    f"vs {c.label.lower()}. Largest driver: {main['name'].lower()} effect ({main['value']:+,.0f})"
                    + (f"; biggest SKU move: {top_sku[0]['name']} ({top_sku[0]['change']:+,.0f})." if top_sku else "."))
        return {
            "brand": brand, "subcategory": subcategory, "product": product,
            "period": p.to_dict(), "comparison": c.to_dict(), "direction": direction,
            "revenue": _r(br["revenue"]), "revenue_prev": _r(br["revenue_prev"]), "change": _r(br["change"]),
            "change_pct": _r(100 * br["change"] / br["revenue_prev"]) if br["revenue_prev"] else None,
            "headline": headline,
            "bridge": bridge_items, "bridge_residual": _r(br["residual"], 6),
            "contributors": {
                "sku": self._contributors("ProductID", f, period, mode, as_of),
                "retailer": self._contributors("Retailer", f, period, mode, as_of),
                "region": self._contributors("Region", f, period, mode, as_of),
                "channel": self._contributors("Channel", f, period, mode, as_of, top=3),
            },
            "causes": causes,
        }
