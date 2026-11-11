"""Page-level payloads for the dashboard, built on the KPI engine.

Each public method returns a JSON-ready dict for one dashboard page, for one
core brand, one period and one set of global filters. FastAPI (api/main.py)
and the LLM tools (llm/tools.py) both call this class, so the dashboard and
the assistant always see the same numbers.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from kpi import registry as R
from kpi import time_intel as T
from kpi.competitive import Competitive
from kpi.diagnostics import Diagnostics
from kpi.engine import Engine
from kpi.filters import Filters
from kpi.health_score import WEIGHTS, health_scores
from pipeline.schema import CORE_BRANDS

ROOT = Path(__file__).resolve().parents[1]
SCORECARD = ["revenue", "units", "asp", "margin", "margin_pct", "discount_pct",
             "promo_revenue_share", "avg_rating", "stockout_risk_pct"]


def jsonable(o):
    """Recursively convert pandas/numpy objects to plain JSON types (NaN -> None)."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return jsonable(o.to_dict(orient="records"))
    if isinstance(o, pd.Series):
        return jsonable(o.to_dict())
    if isinstance(o, (pd.Timestamp, date)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if o is pd.NaT:
        return None
    return o


@dataclass(frozen=True)
class Ctx:
    """Everything that defines what a page shows, besides the brand."""
    period: str | tuple = "YTD"
    mode: str = "yoy"
    as_of: str | None = None
    filters: Filters = Filters()

    def resolved_period(self):
        return self.period


class BrandNotFound(ValueError):
    pass


class Service:
    def __init__(self, engine: Engine | None = None):
        self.e = engine or Engine()
        self.c = Competitive(self.e)
        self.d = Diagnostics(self.e, self.c)
        # lru_cache per instance: page payloads are pure functions of their arguments
        for name in ["overview", "variants", "competitors", "retailers", "marketing", "diagnostics", "health"]:
            setattr(self, name, lru_cache(maxsize=256)(getattr(self, name)))

    # ------------------------------------------------------------------ helpers
    def _check(self, brand: str) -> None:
        if brand not in CORE_BRANDS:
            raise BrandNotFound(f"{brand!r} is not a core brand. Core brands: {', '.join(CORE_BRANDS)}")

    def _bf(self, brand: str, ctx: Ctx) -> Filters:
        return ctx.filters.with_(brands=brand)

    def _periods(self, ctx: Ctx) -> dict:
        p, _ = self.e.period(ctx.period, ctx.as_of)
        c = self.e.comparison_period(ctx.period, ctx.mode, ctx.as_of)
        cov = c.coverage(self.e.data_start, self.e.data_end) if c else None
        return {"period": p.to_dict(), "comparison": c.to_dict() if c else None,
                "comparison_coverage": cov, "mode": ctx.mode, "filters": ctx.filters.active()}

    @staticmethod
    def _grain(days: int) -> str:
        return "D" if days <= 31 else ("W" if days <= 140 else "M")

    def _trend(self, kpi: str, f: Filters, ctx: Ctx, by: str | None = None) -> dict:
        p, _ = self.e.period(ctx.period, ctx.as_of)
        c = self.e.comparison_period(ctx.period, ctx.mode, ctx.as_of)
        grain = self._grain(p.days)
        cur = self.e.timeseries(kpi, grain, f, p, by=by)
        prev = (self.e.timeseries(kpi, grain, f, c, by=by)
                if c is not None and c.coverage(self.e.data_start, self.e.data_end) > 0 else pd.DataFrame())
        return {"grain": grain, "current": cur, "previous": prev}

    # ------------------------------------------------------------------ meta
    def meta(self) -> dict:
        m = self.e.m
        dq_path = ROOT / "reports" / "data_quality.json"
        caveats = []
        if dq_path.exists():
            dq = json.loads(dq_path.read_text())
            caveats = [{"check": r["check"], "severity": r["severity"], "detail": r["detail"]}
                       for r in dq["results"] if not r["passed"] or r["severity"] == "info"]
        brands = []
        for b in CORE_BRANDS:
            p = m.products[m.products["Brand"] == b]
            brands.append({"brand": b, "variants": int(len(p)), "subcategories": sorted(p["SubCategory"].unique()),
                           "has_market_share": b in set(m.market_share["Brand"])})
        return jsonable({
            "core_brands": brands,
            "competitor_brands": sorted(set(m.products["Brand"]) - set(CORE_BRANDS)),
            "presets": [{"id": k, "label": v} for k, v in T.PRESETS.items()],
            "compare_modes": [{"id": k, "label": v} for k, v in T.COMPARE_MODES.items()],
            "data_range": {"start": self.e.data_start, "end": self.e.data_end},
            "filter_options": {
                "retailers": sorted(m.retailers["Retailer"]), "channels": sorted(m.retailers["Channel"].unique()),
                "tiers": sorted(m.retailers["Tier"].unique()), "regions": sorted(m.sales["Region"].unique()),
            },
            "retailers": m.retailers,
            "kpis": [k.to_dict() for k in R.KPIS],
            "caveats": caveats,
        })

    # ------------------------------------------------------------------ pages
    def overview(self, brand: str, ctx: Ctx) -> dict:
        self._check(brand)
        f = self._bf(brand, ctx)
        cards = self.e.scorecard(SCORECARD, f, ctx.period, ctx.mode, ctx.as_of)
        breakdowns = {dim: self.e.breakdown_compare("revenue", dim, f, ctx.period, ctx.mode, ctx.as_of)
                      for dim in ["SubCategory", "Category", "Retailer", "Region", "Channel"]}
        hs = self.health(ctx.period, ctx.mode, ctx.as_of)
        me = next(r for r in hs["brands"] if r["Brand"] == brand)
        return jsonable({
            "brand": brand, **self._periods(ctx),
            "kpis": cards,
            "trend": self._trend("revenue", f, ctx),
            "units_trend": self._trend("units", f, ctx),
            "breakdowns": breakdowns,
            "health": me, "health_weights": WEIGHTS,
            "health_note": "Health Score is computed across all channels and retailers, against all 11 brands.",
        })

    def variants(self, brand: str, ctx: Ctx) -> dict:
        self._check(brand)
        vt = self.c.variant_table(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters)
        cr = self.c.closest_rivals(brand, ctx.period, ctx.as_of, base=ctx.filters)
        # variant x external brand matrix: which rival brands each variant faces
        ext_brands = list(cr["RivalBrand"])
        matrix = []
        for g in vt["groups"]:
            for v in g["variants"]:
                faced = {r["Brand"] for r in v["rivals"] if r["Tier"] == "external"}
                matrix.append({"ProductID": v["ProductID"], "ProductName": v["ProductName"],
                               "SubCategory": v["SubCategory"],
                               "cells": {b: b in faced for b in ext_brands}})
        return jsonable({"brand": brand, **self._periods(ctx), **vt, "closest_rivals": cr,
                         "matrix": {"brands": ext_brands, "rows": matrix}})

    def competitors(self, brand: str, ctx: Ctx) -> dict:
        self._check(brand)
        pos = self.c.price_position(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters)
        msg = self.c.market_share_gap(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters)
        share_brands = ([brand] if msg["available"] else []) + [r["brand"] for r in msg["rivals"]]
        p, _ = self.e.period(ctx.period, ctx.as_of)
        ms = self.e.m.market_share
        # show at least 12 months of share history so a short period still has context
        lo = min(p.start, p.end - pd.DateOffset(months=11)).replace(day=1)
        ms = ms[ms["Brand"].isin(share_brands) & ms["Date"].between(lo, p.end)]
        sub = self.c.subcategory_share(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters)
        # price trend: our ASP vs rivals' ASP per SubCategory, monthly
        price_trend = []
        for row in pos["by_subcategory"]:
            ours = self.e.timeseries("asp", "M", ctx.filters.with_(brands=brand, subcategories=row["SubCategory"]), p)
            theirs = self.e.timeseries("asp", "M", ctx.filters.with_(brands=row["rivals"], subcategories=row["SubCategory"]), p) \
                if row["rivals"] else pd.DataFrame(columns=["bucket", "value"])
            j = ours.rename(columns={"value": "ours"}).merge(
                theirs.rename(columns={"value": "rivals"})[["bucket", "rivals"]], on="bucket", how="outer")
            price_trend.append({"SubCategory": row["SubCategory"], "series": j[["bucket", "ours", "rivals"]]})
        return jsonable({
            "brand": brand, **self._periods(ctx),
            "price_position": pos, "market_share": msg,
            "market_share_series": ms[["Date", "Brand", "MarketSharePct"]],
            "subcategory_share": sub,
            "activity": self.c.activity(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters),
            "answers": self.c.answers(brand, ctx.period, ctx.mode, ctx.as_of, base=ctx.filters),
            "price_trend": price_trend,
        })

    def retailers(self, brand: str, ctx: Ctx) -> dict:
        self._check(brand)
        f = self._bf(brand, ctx)
        kp = ["revenue", "margin", "margin_pct", "asp", "price_index", "promo_lift_pct", "promo_revenue_lift_pct",
              "promo_revenue_share", "units"]
        tbl = None
        for k in kp:
            b = self.e.breakdown_compare(k, "Retailer", f, ctx.period, ctx.mode, ctx.as_of)
            b = b.rename(columns={"current": k, "previous": f"{k}_prev", "delta": f"{k}_delta", "delta_pct": f"{k}_delta_pct"})
            keep = ["Retailer", k, f"{k}_prev"] + ([f"{k}_delta_pct"] if k in ("revenue", "units") else [f"{k}_delta"])
            tbl = b[keep] if tbl is None else tbl.merge(b[keep], on="Retailer", how="outer")
        tbl = tbl.merge(self.e.m.retailers[["Retailer", "Channel", "Tier"]], on="Retailer", how="left")
        tbl["revenue_share_pct"] = 100 * tbl["revenue"] / tbl["revenue"].sum()
        tbl = tbl.sort_values("revenue", ascending=False)

        top = self.e.breakdown("revenue", ["Retailer", "ProductID"], f, ctx.period, ctx.as_of)
        names = self.e.m.products.set_index("ProductID")[["ProductName", "SubCategory"]]
        top = top.join(names, on="ProductID")
        top_skus = {r: g.head(3)[["ProductID", "ProductName", "SubCategory", "value"]]
                    for r, g in top.groupby("Retailer", sort=False)}

        def best(col, label, fmt, higher=True):
            d = tbl.dropna(subset=[col])
            if d.empty:
                return None
            r = d.loc[d[col].idxmax() if higher else d[col].idxmin()]
            return {"question": label, "retailer": r["Retailer"], "value": r[col], "format": fmt}

        answers = [
            best("revenue", "Which retailer drives the most revenue?", "currency"),
            best("margin_pct", "Which retailer has the highest margin?", "pct"),
            best("promo_revenue_lift_pct", "Which retailer responds best to promotions?", "pct"),
            best("revenue_delta_pct", "Which retailer is growing fastest?", "pct"),
        ]
        return jsonable({
            "brand": brand, **self._periods(ctx),
            "table": tbl, "top_skus": top_skus,
            "trend": self._trend("revenue", f, ctx, by="Retailer"),
            "by_tier": self.e.breakdown_compare("revenue", "Tier", f, ctx.period, ctx.mode, ctx.as_of),
            "by_channel": self.e.breakdown_compare("revenue", "Channel", f, ctx.period, ctx.mode, ctx.as_of),
            "answers": [a for a in answers if a],
            "notes": {"price_index": "100 = the same SKUs' average price across all retailers in the selection.",
                      "promo_lift": "Promo vs non-promo transactions in the same promo months."},
        })

    def marketing(self, brand: str, ctx: Ctx) -> dict:
        self._check(brand)
        f = self._bf(brand, ctx)
        promo_kpis = ["promo_revenue_share", "promo_lift_pct", "promo_revenue_lift_pct", "discount_pct"]
        df, _ = self.e.frame("sales", f, self.e.period(ctx.period, ctx.as_of)[0])
        season = df[df["InPromoSeason"]]
        by_type = (season.groupby("Promotion")
                   .agg(transactions=("Transactions", "sum"), revenue=("Revenue", "sum"), units=("UnitsSold", "sum"),
                        units_per_txn=("UnitsSold", "mean"), revenue_per_txn=("Revenue", "mean"),
                        discount_value=("DiscountValue", "sum"), gross=("GrossValue", "sum"))
                   .reset_index())
        by_type["discount_pct"] = 100 * by_type["discount_value"] / by_type["gross"]
        p, _ = self.e.period(ctx.period, ctx.as_of)
        mk, _ = self.e.frame("marketing", None, p)
        campaigns = (mk.groupby(["Campaign", "Channel"])
                     .agg(spend=("Spend", "sum"), impressions=("Impressions", "sum"), conversions=("Conversions", "sum"),
                          return_value=("Spend", lambda s: float((s * mk.loc[s.index, "ROI"]).sum())))
                     .reset_index())
        campaigns["roi"] = campaigns["return_value"] / campaigns["spend"]
        campaigns["conversion_pct"] = 100 * campaigns["conversions"] / campaigns["impressions"]
        return jsonable({
            "brand": brand, **self._periods(ctx),
            "promo_kpis": self.e.scorecard(promo_kpis, f, ctx.period, ctx.mode, ctx.as_of),
            "promo_by_type": by_type.drop(columns=["discount_value", "gross"]),
            "promo_trend": self._trend("promo_revenue_share", f, ctx),
            "promo_by_retailer": self.e.breakdown("promo_revenue_lift_pct", "Retailer", f, ctx.period, ctx.as_of),
            "company": {
                "kpis": self.e.scorecard(["campaign_spend", "campaign_roi", "conversion_rate_pct"], None,
                                         ctx.period, ctx.mode, ctx.as_of),
                "campaigns": campaigns.drop(columns=["return_value"]),
                "spend_trend": self._trend("campaign_spend", None, ctx),
                "note": "The marketing data has no Brand column, so campaign spend and ROI are for the whole company, "
                        "not for " + brand + ".",
            },
        })

    def diagnostics(self, brand: str, ctx: Ctx, subcategory: str | None = None, product: str | None = None) -> dict:
        self._check(brand)
        out = self.d.explain(brand, ctx.period, ctx.mode, ctx.as_of, subcategory=subcategory, product=product,
                             base=ctx.filters)
        return jsonable({**self._periods(ctx), **out})

    def health(self, period="YTD", mode="yoy", as_of=None) -> dict:
        h = health_scores(self.e, period, mode, as_of)
        return jsonable({"brands": h.reset_index(), "weights": WEIGHTS, "period": h.attrs["period"],
                         "comparison": h.attrs["comparison"]})
