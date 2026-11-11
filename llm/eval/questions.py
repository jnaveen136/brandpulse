"""Evaluation questions for the Q&A layer.

Expected answers are computed live from the KPI engine (never hard-coded), so
the set stays correct if the data changes. Each item has:
  q, brand, period, mode   the question and the dashboard context it is asked in
  kind                     lookup | time | breakdown | competitor | diagnostic | health | definition | refusal
  expect(tb)               -> {"numbers": [...]} and/or {"texts": [...]}; any one number OR all texts must appear
  refuse                   True if the right answer is "the data doesn't cover this"
"""
from __future__ import annotations

from kpi.filters import Filters


def _v(tb, kpi, brand, period, **kw):
    return tb.e.value(kpi, Filters.make(brands=brand, **kw), period)


def _c(tb, kpi, brand, period, mode):
    return tb.e.compare(kpi, Filters.make(brands=brand), period, mode)


def _top(tb, kpi, by, brand, period, key="current", mode="yoy"):
    b = tb.e.breakdown_compare(kpi, by, Filters.make(brands=brand), period, mode)
    return b.sort_values(key, ascending=False).iloc[0][by]


def N(*xs):
    return {"numbers": [x for x in xs if x is not None]}


def S(*xs):
    return {"texts": list(xs)}


QUESTIONS = [
    # ---------------- lookups
    dict(q="What is Dettol's revenue this year?", brand="Dettol", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "revenue", "Dettol", "YTD"))),
    dict(q="How many units did Harpic sell last quarter?", brand="Harpic", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "units", "Harpic", "PQ"))),
    dict(q="What is Veet's average selling price year to date?", brand="Veet", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "asp", "Veet", "YTD"))),
    dict(q="What is Mortein's margin percentage this year?", brand="Mortein", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "margin_pct", "Mortein", "YTD"))),
    dict(q="What is Lizol's average discount this year?", brand="Lizol", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "discount_pct", "Lizol", "YTD"))),
    dict(q="What is Dettol's average customer rating this year?", brand="Dettol", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "avg_rating", "Dettol", "YTD"))),
    dict(q="What is Harpic's stock-out risk this month?", brand="Harpic", period="MTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "stockout_risk_pct", "Harpic", "MTD"))),
    dict(q="What share of Veet revenue comes from promotions this year?", brand="Veet", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "promo_revenue_share", "Veet", "YTD"))),
    dict(q="What is Dettol's market share this year?", brand="Dettol", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "market_share", "Dettol", "YTD"))),
    dict(q="What was Lizol's revenue in the last 13 weeks?", brand="Lizol", period="YTD", mode="yoy", kind="lookup",
         expect=lambda t: N(_v(t, "revenue", "Lizol", "L13W"))),
    # ---------------- time intelligence
    dict(q="How did Dettol revenue change this year compared with last year?", brand="Dettol", period="YTD", mode="yoy", kind="time",
         expect=lambda t: N(_c(t, "revenue", "Dettol", "YTD", "yoy")["delta_pct"], _c(t, "revenue", "Dettol", "YTD", "yoy")["delta"])),
    dict(q="How did Harpic revenue this month compare with last month?", brand="Harpic", period="MTD", mode="previous", kind="time",
         expect=lambda t: N(_c(t, "revenue", "Harpic", "MTD", "previous")["delta_pct"], _c(t, "revenue", "Harpic", "MTD", "previous")["delta"])),
    dict(q="How did Veet's units last quarter compare with the quarter before?", brand="Veet", period="PQ", mode="previous", kind="time",
         expect=lambda t: N(_c(t, "units", "Veet", "PQ", "previous")["delta_pct"], _c(t, "units", "Veet", "PQ", "previous")["delta"])),
    dict(q="Mortein revenue in the last 30 days versus the 30 days before?", brand="Mortein", period="R30", mode="previous", kind="time",
         expect=lambda t: N(_c(t, "revenue", "Mortein", "R30", "previous")["delta_pct"], _c(t, "revenue", "Mortein", "R30", "previous")["delta"])),
    dict(q="How is Lizol revenue quarter to date versus the same period last year?", brand="Lizol", period="QTD", mode="yoy", kind="time",
         expect=lambda t: N(_c(t, "revenue", "Lizol", "QTD", "yoy")["delta_pct"], _c(t, "revenue", "Lizol", "QTD", "yoy")["delta"])),
    dict(q="What was Dettol's revenue last month?", brand="Dettol", period="YTD", mode="yoy", kind="time",
         expect=lambda t: N(_v(t, "revenue", "Dettol", "PM"))),
    dict(q="What is Harpic's revenue week to date?", brand="Harpic", period="YTD", mode="yoy", kind="time",
         expect=lambda t: N(_v(t, "revenue", "Harpic", "WTD"))),
    dict(q="What is Veet's revenue over the rolling 90 days?", brand="Veet", period="YTD", mode="yoy", kind="time",
         expect=lambda t: N(_v(t, "revenue", "Veet", "R90"))),
    # ---------------- breakdowns / retailers
    dict(q="Which retailer drives the most revenue for Dettol this year?", brand="Dettol", period="YTD", mode="yoy", kind="breakdown",
         expect=lambda t: S(_top(t, "revenue", "Retailer", "Dettol", "YTD"))),
    dict(q="Which retailer has the highest margin percentage for Harpic this year?", brand="Harpic", period="YTD", mode="yoy", kind="breakdown",
         expect=lambda t: S(_top(t, "margin_pct", "Retailer", "Harpic", "YTD"))),
    dict(q="Which region brings Veet the most revenue this year?", brand="Veet", period="YTD", mode="yoy", kind="breakdown",
         expect=lambda t: S(_top(t, "revenue", "Region", "Veet", "YTD"))),
    dict(q="Which Lizol sub-category earns the most revenue this year?", brand="Lizol", period="YTD", mode="yoy", kind="breakdown",
         expect=lambda t: S(_top(t, "revenue", "SubCategory", "Lizol", "YTD"))),
    dict(q="Which channel is growing fastest for Mortein this year compared with last year?", brand="Mortein", period="YTD", mode="yoy", kind="breakdown",
         expect=lambda t: S(_top(t, "revenue", "Channel", "Mortein", "YTD", key="delta_pct"))),
    # ---------------- competitors
    dict(q="Who is Dettol's closest external rival?", brand="Dettol", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: S(t.s.c.closest_rivals("Dettol", "YTD").iloc[0]["RivalBrand"])),
    dict(q="Who is discounting the most in Harpic's sub-categories this year?", brand="Harpic", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: S(t.s.c.answers("Harpic", "YTD", "yoy")["who_is_discounting"]["rivals"][0]["brand"])),
    dict(q="Which competitor gained the most share in Veet's sub-categories this year?", brand="Veet", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: S(t.s.c.answers("Veet", "YTD", "yoy")["who_gained_share"]["subcategory_share"][0]["Brand"])),
    dict(q="What is Lizol's price gap versus competitors this year?", brand="Lizol", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: N(t.s.c.price_position("Lizol", "YTD", "yoy")["price_gap_pct"])),
    dict(q="What is the market share gap between Dettol and Lifebuoy this year?", brand="Dettol", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: N(_v(t, "market_share", "Dettol", "YTD") - _v(t, "market_share", "Lifebuoy", "YTD"))),
    dict(q="Which external brands compete with Dettol Variant 1?", brand="Dettol", period="YTD", mode="yoy", kind="competitor",
         expect=lambda t: S("Domex", "Ariel", "Head & Shoulders")),
    dict(q="Did any competitor manufacturer launch a product last quarter?", brand="Dettol", period="PQ", mode="yoy", kind="competitor",
         expect=lambda t: S(*sorted({e["competitor"] for e in t.s.c.activity("Dettol", "PQ", "yoy")["events"] if e["event"] == "New Launch"}) or ["no"])),
    # ---------------- diagnostics
    dict(q="Why did Harpic revenue change this month compared with last month?", brand="Harpic", period="MTD", mode="previous", kind="diagnostic",
         expect=lambda t: N(t.s.d.explain("Harpic", "MTD", "previous")["change"], t.s.d.explain("Harpic", "MTD", "previous")["change_pct"])),
    dict(q="Why did Dettol revenue fall this year?", brand="Dettol", period="YTD", mode="yoy", kind="diagnostic",
         expect=lambda t: N(t.s.d.explain("Dettol", "YTD", "yoy")["change"], t.s.d.explain("Dettol", "YTD", "yoy")["change_pct"])),
    dict(q="What drove Mortein's revenue change last month compared with the month before?", brand="Mortein", period="PM", mode="previous", kind="diagnostic",
         expect=lambda t: N(t.s.d.explain("Mortein", "PM", "previous")["change"], t.s.d.explain("Mortein", "PM", "previous")["change_pct"])),
    # ---------------- health
    dict(q="What is Veet's brand health score?", brand="Veet", period="YTD", mode="yoy", kind="health",
         expect=lambda t: N(next(r["health_score"] for r in t.s.health("YTD", "yoy")["brands"] if r["Brand"] == "Veet"))),
    dict(q="Which Reckitt brand has the highest brand health score?", brand="Dettol", period="YTD", mode="yoy", kind="health",
         expect=lambda t: S(next(r["Brand"] for r in t.s.health("YTD", "yoy")["brands"] if r["IsCore"]))),
    # ---------------- definitions
    dict(q="How is the competitor activity index calculated?", brand="Dettol", period="YTD", mode="yoy", kind="definition",
         expect=lambda t: S("price cut", "launch")),
    dict(q="How are competitors matched to our variants?", brand="Dettol", period="YTD", mode="yoy", kind="definition",
         expect=lambda t: S("sub")),
    # ---------------- should refuse / qualify
    dict(q="What is Lizol's market share?", brand="Lizol", period="YTD", mode="yoy", kind="refusal", refuse=True, expect=lambda t: {}),
    dict(q="What is Mortein's market share trend this year?", brand="Mortein", period="YTD", mode="yoy", kind="refusal", refuse=True, expect=lambda t: {}),
    dict(q="How much did we spend on marketing for Dettol specifically?", brand="Dettol", period="YTD", mode="yoy", kind="refusal", refuse=True, expect=lambda t: {}),
    dict(q="What will Dettol revenue be next quarter?", brand="Dettol", period="YTD", mode="yoy", kind="refusal", refuse=True, expect=lambda t: {}),
    dict(q="What was Harpic's revenue in 2023?", brand="Harpic", period="YTD", mode="yoy", kind="refusal", refuse=True, expect=lambda t: {}),
]
