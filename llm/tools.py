"""Tools the LLM can call. They are the only way it gets numbers.

Every argument is validated against the KPI registry, the brand list and the
Time Intelligence presets before anything runs; a bad argument comes back as
an error message the model can correct, never as a guessed number. Results
are compact JSON with numbers rounded to 2 decimals, and say explicitly when
the data does not cover what was asked ("available": false).
"""
from __future__ import annotations

import json
from typing import Any

from api.service import Ctx, Service, jsonable
from kpi import registry as R
from kpi import time_intel as T
from kpi.filters import Filters
from pipeline.schema import CORE_BRANDS

from .knowledge import Knowledge

BREAKDOWN_DIMS = {"Retailer": "Retailer", "Region": "Region", "Channel": "Channel", "Tier": "Tier",
                  "SubCategory": "SubCategory", "Category": "Category", "Variant": "ProductName", "Brand": "Brand"}
PRESET_TEXT = ", ".join(f"{k} ({v})" for k, v in T.PRESETS.items())


class ToolError(ValueError):
    pass


def _r(o):
    """Round floats for the model: 2 decimals is enough and avoids noisy copies."""
    if isinstance(o, dict):
        return {k: _r(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_r(v) for v in o]
    if isinstance(o, float):
        return round(o, 2)
    return o


def specs(all_brands: list[str]) -> list[dict]:
    kpi_ids = [k.id for k in R.KPIS]
    period = {"type": "string", "enum": list(T.PRESETS), "description": f"Time Intelligence preset: {PRESET_TEXT}"}
    mode = {"type": "string", "enum": ["yoy", "previous"], "description": "Compare with same period last year (yoy) or the previous period"}
    core = {"type": "string", "enum": CORE_BRANDS, "description": "A Reckitt core brand"}

    def fn(name, desc, props, required):
        return {"type": "function", "function": {"name": name, "description": desc,
                                                 "parameters": {"type": "object", "properties": props, "required": required}}}

    return [
        fn("get_kpi", "One KPI for one brand (any of the 11) over a period, with its comparison value and change. "
           "Use for revenue, units, ASP, margin, discount, promo, rating, stock-out, market share, campaign and competitor-activity KPIs.",
           {"kpi": {"type": "string", "enum": kpi_ids}, "brand": {"type": "string", "enum": all_brands},
            "period": period, "mode": mode,
            "subcategory": {"type": "string", "description": "Optional sub-category filter (Cleaner, Cream, Liquid, Soap, Spray)"},
            "retailer": {"type": "string", "description": "Optional retailer filter"},
            "region": {"type": "string", "description": "Optional region filter (North, South, East, West)"}},
           ["kpi", "brand"]),
        fn("get_breakdown", "A KPI split by a dimension (e.g. revenue by Retailer) for one brand, with each group's change.",
           {"kpi": {"type": "string", "enum": kpi_ids}, "by": {"type": "string", "enum": list(BREAKDOWN_DIMS)},
            "brand": {"type": "string", "enum": all_brands}, "period": period, "mode": mode},
           ["kpi", "by", "brand"]),
        fn("get_trend", "A KPI over time (by month, week or day) for one brand.",
           {"kpi": {"type": "string", "enum": kpi_ids}, "brand": {"type": "string", "enum": all_brands}, "period": period,
            "grain": {"type": "string", "enum": ["D", "W", "M", "Q"]}},
           ["kpi", "brand"]),
        fn("get_competitors", "Competitive picture for a core brand vs its real rivals (external SKUs in the same sub-categories): "
           "closest rivals, price gap, discounting by rival, share gains, competitor launches and price cuts, market share gap.",
           {"brand": core, "period": period, "mode": mode}, ["brand"]),
        fn("get_variants", "Each variant of a core brand with its revenue, growth, price gap vs external rivals and which rival brands it faces.",
           {"brand": core, "period": period, "mode": mode}, ["brand"]),
        fn("explain_change", "Why a core brand's revenue changed between the period and its comparison: exact volume/mix/price bridge, "
           "checked causes (promotions, competitor discounting/events, share shift, stock-outs, ratings) and top contributors.",
           {"brand": core, "period": period, "mode": mode,
            "subcategory": {"type": "string", "description": "Optional: limit to one sub-category"}}, ["brand"]),
        fn("get_health_scores", "Brand Health Score (0-100) for all 11 brands with its components.", {"period": period}, []),
        fn("search_knowledge", "Search KPI definitions, formulas, business rules (e.g. how competitors are matched) and data caveats "
           "(e.g. which brands lack market share). Use for 'what is', 'how is X calculated', 'why is X missing'.",
           {"query": {"type": "string"}}, ["query"]),
    ]


class Toolbox:
    def __init__(self, service: Service | None = None):
        self.s = service or Service()
        self.e = self.s.e
        self.brands = sorted(self.e.m.products["Brand"].unique())
        self.kb = Knowledge(self.s)
        self.specs = specs(self.brands)

    # ------------------------------------------------------------------ validation
    def _brand(self, b, core_only=False):
        if not b:
            raise ToolError("brand is required")
        match = next((x for x in self.brands if x.lower() == str(b).lower()), None)
        if not match:
            raise ToolError(f"Unknown brand {b!r}. Brands: {', '.join(self.brands)}")
        if core_only and match not in CORE_BRANDS:
            raise ToolError(f"{match} is a competitor brand; this tool needs a Reckitt core brand: {', '.join(CORE_BRANDS)}")
        return match

    @staticmethod
    def _period(p):
        p = (p or "YTD").upper()
        if p not in T.PRESETS:
            raise ToolError(f"Unknown period {p!r}. Use one of: {PRESET_TEXT}")
        return p

    @staticmethod
    def _mode(m):
        m = (m or "yoy").lower()
        if m not in ("yoy", "previous"):
            raise ToolError("mode must be 'yoy' or 'previous'")
        return m

    @staticmethod
    def _kpi(k):
        try:
            return R.get(k)
        except KeyError:
            raise ToolError(f"Unknown KPI {k!r}. Known: {', '.join(x.id for x in R.KPIS)}") from None

    def _check_value(self, col: str, val: str | None) -> str | None:
        if not val:
            return None
        src = self.e.m.sales if col != "Retailer" else self.e.m.retailers
        options = sorted(src[col].unique())
        match = next((o for o in options if o.lower() == str(val).lower()), None)
        if not match:
            raise ToolError(f"Unknown {col} {val!r}. Options: {', '.join(options)}")
        return match

    # ------------------------------------------------------------------ tools
    def get_kpi(self, kpi, brand, period=None, mode=None, subcategory=None, retailer=None, region=None):
        k, b, p, m = self._kpi(kpi), self._brand(brand), self._period(period), self._mode(mode)
        f = Filters.make(brands=b, subcategories=self._check_value("SubCategory", subcategory),
                         retailers=self._check_value("Retailer", retailer), regions=self._check_value("Region", region))
        if k.source == "events":  # competitor activity: the manufacturers of this brand's external rivals
            mfrs = self.s.c.rival_manufacturers(b) if b in CORE_BRANDS else ["Unilever", "P&G", "SC Johnson"]
            f = Filters.make(manufacturers=mfrs)
        res = self.e.compare(k.id, f, p, m)
        out = {"kpi": k.id, "name": k.name, "unit": k.unit, "brand": b,
               "filters": {x: y for x, y in {"subcategory": subcategory, "retailer": retailer, "region": region}.items() if y},
               "value": res["current"], "comparison_value": res["previous"],
               ("change_pp" if k.unit == "pct" else "change_pct"): res["delta"] if k.unit == "pct" else res["delta_pct"],
               "period": res["period"], "comparison_period": res["comparison"],
               "definition": k.description, "higher_is_better": k.higher_is_better}
        if k.kind == "growth":
            out["value_is"] = f"% change of {R.get(k.base).name} vs the comparison period"
        if res["current"] is None:
            out["available"] = False
            out["reason"] = k.scope_note or "No data for this selection."
        if res["ignored_filters"]:
            out["note"] = (f"{k.name} is not recorded by {', '.join(res['ignored_filters'])}; this is the "
                           f"{'company-wide' if k.source == 'marketing' else 'unfiltered'} value. {k.scope_note}").strip()
        if k.source == "events":
            out["note"] = f"Competitor events of {', '.join(f.manufacturers)} (recorded per manufacturer, not per brand)."
        return out

    def get_breakdown(self, kpi, by, brand, period=None, mode=None):
        k, b, p, m = self._kpi(kpi), self._brand(brand), self._period(period), self._mode(mode)
        if by not in BREAKDOWN_DIMS:
            raise ToolError(f"by must be one of {list(BREAKDOWN_DIMS)}")
        col = BREAKDOWN_DIMS[by]
        if k.kind == "growth":
            k = R.get(k.base)
        if k.source != "sales" and col not in ("Brand", "SubCategory", "Category", "ProductName"):
            raise ToolError(f"{k.name} is not recorded by {by}")
        rows = self.e.breakdown_compare(k.id, col, Filters.make(brands=b), p, m).head(15)
        return {"kpi": k.id, "name": k.name, "unit": k.unit, "brand": b, "by": by,
                "period": self.e.period(p)[0].to_dict(),
                "rows": [{by: r[col], "value": r["current"], "comparison_value": r["previous"],
                          "change_pct": r["delta_pct"], **({"change_pp": r["delta"]} if k.unit == "pct" else {})}
                         for _, r in rows.iterrows()]}

    def get_trend(self, kpi, brand, period=None, grain=None):
        k, b, p = self._kpi(kpi), self._brand(brand), self._period(period)
        if k.kind == "growth":
            raise ToolError("Use the base KPI (e.g. revenue) for trends")
        ts = self.e.timeseries(k.id, grain or "M", Filters.make(brands=b), p).tail(31)
        return {"kpi": k.id, "name": k.name, "unit": k.unit, "brand": b, "grain": grain or "M",
                "points": [{"start": r["bucket"].strftime("%Y-%m-%d"), "value": r["value"], "partial": bool(r["partial"])}
                           for _, r in ts.iterrows()]}

    def get_competitors(self, brand, period=None, mode=None):
        b, p, m = self._brand(brand, core_only=True), self._period(period), self._mode(mode)
        c = self.s.competitors(b, Ctx(p, m))
        cr = self.s.c.closest_rivals(b, p)
        pp = c["price_position"]
        ans = c["answers"]
        return {
            "brand": b, "period": c["period"], "comparison_period": c["comparison"],
            "closest_rivals": [{"brand": r.RivalBrand, "manufacturer": r.RivalManufacturer,
                                "variants_overlapped": int(r.variants_overlapped), "of_variants": int(r.total_variants),
                                "subcategories": list(r.subcategories)} for r in cr.itertuples()],
            "price_gap_pct": pp["price_gap_pct"], "price_gap_pct_comparison": pp["price_gap_pct_prev"],
            "our_discount_pct": pp["our_discount_pct"], "competitor_discount_pct": pp["competitor_discount_pct"],
            "competitor_discount_pct_comparison": pp["competitor_discount_pct_prev"],
            "price_by_subcategory": [{k: r[k] for k in ("SubCategory", "rivals", "our_asp", "rival_asp", "price_gap_pct",
                                                        "our_discount_pct", "rival_discount_pct")} for r in pp["by_subcategory"]],
            "who_is_discounting": ans["who_is_discounting"]["rivals"],
            "share_of_subcategory_change": ans["who_gained_share"]["subcategory_share"],
            "market_share": {k: c["market_share"][k] for k in ("available", "our_share", "our_share_prev", "our_change_pp", "rivals", "note")},
            "competitor_launches": ans["who_launched"]["launches"], "competitor_price_cuts": ans["who_launched"]["price_cuts"],
            "activity_index": c["activity"]["index"], "activity_index_comparison": c["activity"]["index_prev"],
            "notes": ["Rivals = external (Unilever/P&G) SKUs in the same sub-categories as this brand.",
                      "Share of sub-category is among the 11 tracked brands.", ans["who_launched"]["note"]],
        }

    def get_variants(self, brand, period=None, mode=None):
        b, p, m = self._brand(brand, core_only=True), self._period(period), self._mode(mode)
        v = self.s.variants(b, Ctx(p, m))
        out = []
        for g in v["groups"]:
            for x in g["variants"]:
                out.append({"variant": x["ProductName"], "subcategory": x["SubCategory"], "category": x["Category"],
                            "revenue": x["revenue"], "revenue_growth_pct": x["revenue_growth_pct"], "units": x["units"],
                            "asp": x["asp"], "margin_pct": x["margin_pct"], "avg_rating": x["avg_rating"],
                            "price_gap_vs_external_pct": x["price_gap_pct"], "external_rival_brands": x["external_brands"],
                            "other_reckitt_rivals": sorted({r["Brand"] for r in x["rivals"] if r["Tier"] == "reckitt"})})
        return {"brand": b, "period": v["period"], "variants": out}

    def explain_change(self, brand, period=None, mode=None, subcategory=None):
        b, p, m = self._brand(brand, core_only=True), self._period(period), self._mode(mode)
        sc = self._check_value("SubCategory", subcategory)
        d = self.s.diagnostics(b, Ctx(p, m), sc)
        if "error" in d:
            return {"available": False, "reason": d["error"]}
        return {k: d[k] for k in ("brand", "subcategory", "period", "comparison", "revenue", "revenue_prev", "change",
                                  "change_pct", "headline", "bridge", "contributors")} | {
            "causes": [{k: c[k] for k in ("title", "supporting", "effect", "impact", "share_of_change", "text")} for c in d["causes"]],
            "note": "supporting=true causes point the same way as the revenue change; effect -1 pushed revenue down, +1 up."}

    def get_health_scores(self, period=None):
        p = self._period(period)
        h = self.s.health(p, "yoy")
        return {"period": h["period"], "comparison": h["comparison"], "weights": h["weights"],
                "brands": [{k: r[k] for k in ("Brand", "IsCore", "health_score", "rank", "growth", "margin", "rating",
                                              "position", "position_source")} for r in h["brands"]],
                "note": "position_source=proxy means no market-share data; Premium Retailer Share change is used instead."}

    def search_knowledge(self, query):
        return {"query": query, "results": self.kb.search(query, k=4)}

    # ------------------------------------------------------------------ dispatch
    def run(self, name: str, args: dict[str, Any]) -> dict:
        fn = getattr(self, name, None)
        if name.startswith("_") or not callable(fn) or name not in {s["function"]["name"] for s in self.specs}:
            return {"error": f"Unknown tool {name!r}"}
        try:
            return _r(jsonable(fn(**(args or {}))))
        except ToolError as e:
            return {"error": str(e)}
        except TypeError as e:
            return {"error": f"Bad arguments for {name}: {e}"}

    @staticmethod
    def dumps(result: dict) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
