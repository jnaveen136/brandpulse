"""Competitive layer: who competes with whom, and how a core brand compares.

Mapping rule (confirmed with the mentor): a core variant competes with every
other SKU that has the same SubCategory. Category is ignored. Every rival is
put in one of three tiers:

  self      the same brand's other variants (cannibalisation view)
  reckitt   other Reckitt core brands (portfolio overlap)
  external  Unilever / P&G brands (the real competitive threat)

Competitor KPIs for a selected core brand are always computed against its
*own* competitive set, i.e. the external SKUs in the SubCategories the brand
sells, never against all competitor brands.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.schema import CORE_BRANDS

from .engine import Engine, PeriodLike, _clean
from .filters import Filters

TIERS = ("self", "reckitt", "external")
VARIANT_KPIS = ["revenue", "units", "asp", "margin_pct", "discount_pct", "promo_revenue_share", "avg_rating"]


# ----------------------------------------------------------------------------- mapping
def competitor_map(products: pd.DataFrame) -> pd.DataFrame:
    """One row per (core variant, rival SKU) pair in the same SubCategory."""
    core = products[products["Brand"].isin(CORE_BRANDS)]
    pairs = core.merge(products, on="SubCategory", suffixes=("", "_rival"))
    pairs = pairs[pairs["ProductID"] != pairs["ProductID_rival"]]
    pairs["Tier"] = np.select(
        [pairs["Brand_rival"] == pairs["Brand"], pairs["Brand_rival"].isin(CORE_BRANDS)],
        ["self", "reckitt"], "external")
    out = pairs.rename(columns={
        "Brand": "CoreBrand", "ProductID": "CoreProductID", "ProductName": "CoreProductName",
        "Category": "CoreCategory", "ProductID_rival": "RivalProductID", "ProductName_rival": "RivalProductName",
        "Brand_rival": "RivalBrand", "Manufacturer_rival": "RivalManufacturer", "Category_rival": "RivalCategory",
    })[["CoreBrand", "CoreProductID", "CoreProductName", "CoreCategory", "SubCategory", "Tier",
        "RivalProductID", "RivalProductName", "RivalBrand", "RivalManufacturer", "RivalCategory"]]
    order = {t: i for i, t in enumerate(TIERS)}
    return out.sort_values(["CoreBrand", "SubCategory", "CoreProductID", "Tier", "RivalBrand", "RivalProductID"],
                           key=lambda s: s.map(order) if s.name == "Tier" else s).reset_index(drop=True)


class Competitive:
    def __init__(self, engine: Engine):
        self.e = engine
        self.products = engine.m.products
        self.map = competitor_map(self.products)

    # ------------------------------------------------------------------ the set
    def external_rivals(self, brand: str, subcategory: str | None = None) -> pd.DataFrame:
        m = self.map[(self.map["CoreBrand"] == brand) & (self.map["Tier"] == "external")]
        if subcategory:
            m = m[m["SubCategory"] == subcategory]
        return m

    def subcategories(self, brand: str) -> list[str]:
        return sorted(self.products[self.products["Brand"] == brand]["SubCategory"].unique())

    def rival_manufacturers(self, brand: str) -> list[str]:
        return sorted(self.external_rivals(brand)["RivalManufacturer"].unique())

    def closest_rivals(self, brand: str, period: PeriodLike = "YTD", as_of=None) -> pd.DataFrame:
        """External brands ranked by how many of `brand`'s variants they compete with.
        Ties are broken by the rival's revenue in the shared SubCategories."""
        ext = self.external_rivals(brand)
        n_var = int((self.products["Brand"] == brand).sum())
        g = ext.groupby(["RivalBrand", "RivalManufacturer"]).agg(
            variants_overlapped=("CoreProductID", "nunique"),
            subcategories=("SubCategory", lambda s: sorted(s.unique())),
            rival_skus=("RivalProductID", "nunique"),
        ).reset_index()
        rev = []
        for _, r in g.iterrows():
            f = Filters.make(brands=r["RivalBrand"], subcategories=r["subcategories"])
            rev.append(self.e.value("revenue", f, period, as_of))
        g["shared_subcategory_revenue"] = rev
        g["total_variants"] = n_var
        g = g.sort_values(["variants_overlapped", "shared_subcategory_revenue"], ascending=False).reset_index(drop=True)
        g["rank"] = np.arange(1, len(g) + 1)
        return g

    # ------------------------------------------------------------------ variants
    def variant_table(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> dict:
        """Each core variant with its KPIs and its tiered rivals' KPIs, grouped by SubCategory.

        Returns a JSON-ready dict used by the dashboard's Variants & Competitors page."""
        m = self.map[self.map["CoreBrand"] == brand]
        ids = sorted(set(m["CoreProductID"]) | set(m["RivalProductID"]))
        f = Filters.make(products=ids)
        kp = {}
        for k in VARIANT_KPIS:
            b = self.e.breakdown_compare(k, "ProductID", f, period, mode, as_of).set_index("ProductID")
            kp[k] = b
        prods = self.products.set_index("ProductID")

        def metrics(pid):
            out = {}
            for k in VARIANT_KPIS:
                row = kp[k].loc[pid] if pid in kp[k].index else None
                out[k] = None if row is None else _clean(row["current"])
                out[f"{k}_prev"] = None if row is None else _clean(row["previous"])
            out["revenue_growth_pct"] = (None if not out["revenue_prev"] or out["revenue"] is None
                                         else 100 * (out["revenue"] / out["revenue_prev"] - 1))
            return out

        groups = []
        for sc, gsc in m.groupby("SubCategory"):
            variants = []
            for pid, gv in gsc.groupby("CoreProductID"):
                p = prods.loc[pid]
                rivals = []
                for _, r in gv.iterrows():
                    rivals.append({"ProductID": r["RivalProductID"], "ProductName": r["RivalProductName"],
                                   "Brand": r["RivalBrand"], "Manufacturer": r["RivalManufacturer"],
                                   "Category": r["RivalCategory"], "Tier": r["Tier"],
                                   **metrics(r["RivalProductID"])})
                ext = [x for x in rivals if x["Tier"] == "external"]
                me = metrics(pid)
                ext_rev = sum(x["revenue"] or 0 for x in ext)
                ext_units = sum(x["units"] or 0 for x in ext)
                ext_asp = ext_rev / ext_units if ext_units else None
                variants.append({
                    "ProductID": pid, "ProductName": p["ProductName"], "Category": p["Category"],
                    "SubCategory": sc, "MRP": float(p["MRP"]), **me,
                    "external_avg_asp": ext_asp,
                    "price_gap_pct": None if not ext_asp or me["asp"] is None else 100 * (me["asp"] / ext_asp - 1),
                    "external_brands": sorted({x["Brand"] for x in ext}),
                    "rivals": rivals,
                })
            groups.append({"SubCategory": sc, "variants": variants})
        return {"brand": brand, "groups": groups}

    # ------------------------------------------------------------------ competitor KPIs
    def _subcat_compare(self, brand: str, kpi: str, period, mode, as_of) -> pd.DataFrame:
        """Our KPI vs. external rivals' KPI per SubCategory, current and previous."""
        rows = []
        for sc in self.subcategories(brand):
            rivals = sorted(self.external_rivals(brand, sc)["RivalBrand"].unique())
            ours = self.e.compare(kpi, Filters.make(brands=brand, subcategories=sc), period, mode, as_of)
            theirs = (self.e.compare(kpi, Filters.make(brands=rivals, subcategories=sc), period, mode, as_of)
                      if rivals else {"current": None, "previous": None})
            weight = self.e.value("revenue", Filters.make(brands=brand, subcategories=sc), period, as_of) or 0
            rows.append({"SubCategory": sc, "rivals": rivals, "ours": ours["current"], "ours_prev": ours["previous"],
                         "theirs": theirs["current"], "theirs_prev": theirs["previous"], "weight": weight})
        return pd.DataFrame(rows)

    @staticmethod
    def _weighted(df: pd.DataFrame, col: str) -> float | None:
        d = df.dropna(subset=[col])
        return None if d.empty or d["weight"].sum() == 0 else float((d[col] * d["weight"]).sum() / d["weight"].sum())

    def price_position(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> dict:
        """Price Gap % (our ASP vs rivals' ASP, same SubCategory) and Discount Gap (pp).
        Brand-level values are weighted by our revenue in each SubCategory, so a brand is
        compared like for like (Soap vs Soap), not on its product mix."""
        asp = self._subcat_compare(brand, "asp", period, mode, as_of)
        disc = self._subcat_compare(brand, "discount_pct", period, mode, as_of)
        asp["price_gap_pct"] = 100 * (asp["ours"] / asp["theirs"] - 1)
        asp["price_gap_pct_prev"] = 100 * (asp["ours_prev"] / asp["theirs_prev"] - 1)
        disc["discount_gap_pp"] = disc["ours"] - disc["theirs"]
        disc["discount_gap_pp_prev"] = disc["ours_prev"] - disc["theirs_prev"]
        by_sc = asp[["SubCategory", "rivals", "ours", "theirs", "price_gap_pct", "price_gap_pct_prev", "weight"]].rename(
            columns={"ours": "our_asp", "theirs": "rival_asp"})
        by_sc = by_sc.merge(disc[["SubCategory", "ours", "theirs", "discount_gap_pp", "discount_gap_pp_prev"]].rename(
            columns={"ours": "our_discount_pct", "theirs": "rival_discount_pct"}), on="SubCategory")
        disc_prev = disc.assign(theirs_w=disc["theirs_prev"])
        return {
            "price_gap_pct": self._weighted(by_sc, "price_gap_pct"),
            "price_gap_pct_prev": self._weighted(by_sc, "price_gap_pct_prev"),
            "discount_gap_pp": self._weighted(by_sc, "discount_gap_pp"),
            "discount_gap_pp_prev": self._weighted(by_sc, "discount_gap_pp_prev"),
            "competitor_discount_pct": self._weighted(disc.rename(columns={"theirs": "x"}), "x"),
            "competitor_discount_pct_prev": self._weighted(disc_prev.rename(columns={"theirs_w": "x"}), "x"),
            "our_discount_pct": self._weighted(disc.rename(columns={"ours": "x"}), "x"),
            "by_subcategory": by_sc.replace({np.nan: None}).to_dict(orient="records"),
        }

    def market_share_gap(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> dict:
        """Our market share vs. each external rival that has share data."""
        have = set(self.e.m.market_share["Brand"])
        ours = self.e.compare("market_share", Filters.make(brands=brand), period, mode, as_of) if brand in have else None
        rivals = [b for b in self.closest_rivals(brand, period, as_of)["RivalBrand"] if b in have]
        rows = []
        for r in rivals:
            c = self.e.compare("market_share", Filters.make(brands=r), period, mode, as_of)
            rows.append({"brand": r, "share": c["current"], "share_prev": c["previous"], "change_pp": c["delta"],
                         "gap_pp": None if ours is None or ours["current"] is None else ours["current"] - c["current"]})
        return {
            "available": ours is not None,
            "our_share": None if ours is None else ours["current"],
            "our_share_prev": None if ours is None else ours["previous"],
            "our_change_pp": None if ours is None else ours["delta"],
            "rivals": rows,
            "note": ("Market share is measured within the 6 brands that have share data."
                     if ours is not None else
                     f"No market-share data for {brand}. Use Share of SubCategory (tracked brands) instead."),
        }

    def subcategory_share(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> pd.DataFrame:
        """Share of each SubCategory's revenue (across all 11 tracked brands) held by `brand`
        and by each external rival. A within-dataset measure, labelled as such."""
        rows = []
        for sc in self.subcategories(brand):
            tot = self.e.compare("revenue", Filters.make(subcategories=sc), period, mode, as_of)
            players = [brand] + sorted(self.external_rivals(brand, sc)["RivalBrand"].unique())
            for b in players:
                c = self.e.compare("revenue", Filters.make(brands=b, subcategories=sc), period, mode, as_of)
                share = None if not tot["current"] else 100 * (c["current"] or 0) / tot["current"]
                prev = None if not tot["previous"] else 100 * (c["previous"] or 0) / tot["previous"]
                rows.append({"SubCategory": sc, "Brand": b, "is_focus": b == brand, "share_pct": share,
                             "share_pct_prev": prev,
                             "change_pp": None if share is None or prev is None else share - prev,
                             "revenue": c["current"], "revenue_growth_pct": c["delta_pct"]})
        return pd.DataFrame(rows)

    def activity(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> dict:
        """Competitor Activity Index and the events behind it, for the manufacturers of
        `brand`'s external rivals."""
        mfrs = self.rival_manufacturers(brand)
        f = Filters.make(manufacturers=mfrs)
        idx = self.e.compare("competitor_activity_index", f, period, mode, as_of)
        p, _ = self.e.period(period, as_of)
        ev, _ = self.e.frame("events", f, p)
        return {"manufacturers": mfrs, "index": idx["current"], "index_prev": idx["previous"],
                "change_pct": idx["delta_pct"],
                "events": [{"date": d.strftime("%Y-%m-%d"), "competitor": c, "event": e, "price_impact_pct": float(i)}
                           for d, c, e, i in ev[["Date", "Competitor", "Event", "PriceImpactPct"]].itertuples(index=False)],
                "note": "Events are recorded per manufacturer, not per brand."}

    # ------------------------------------------------------------------ answer cards
    def answers(self, brand: str, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None) -> dict:
        """Direct answers to the mentor's competitor questions, for `brand`'s competitive set."""
        rivals = sorted(self.external_rivals(brand)["RivalBrand"].unique())
        subcats = self.subcategories(brand)
        disc = []
        for r in rivals:
            sc = sorted(self.external_rivals(brand).query("RivalBrand == @r")["SubCategory"].unique())
            c = self.e.compare("discount_pct", Filters.make(brands=r, subcategories=sc), period, mode, as_of)
            disc.append({"brand": r, "discount_pct": c["current"], "discount_pct_prev": c["previous"], "change_pp": c["delta"]})
        disc.sort(key=lambda x: -(x["discount_pct"] or 0))
        ours_disc = self.e.compare("discount_pct", Filters.make(brands=brand), period, mode, as_of)

        share = self.subcategory_share(brand, period, mode, as_of)
        ext = share[~share["is_focus"]].dropna(subset=["change_pp"])
        gained = (ext.groupby("Brand").apply(
            lambda g: pd.Series({"change_pp": float((g["change_pp"] * g["share_pct"].fillna(0)).sum() / max(g["share_pct"].fillna(0).sum(), 1e-9)),
                                 "subcategories": sorted(g["SubCategory"])}), include_groups=False)
                  .sort_values("change_pp", ascending=False).reset_index())
        ms = self.market_share_gap(brand, period, mode, as_of)

        act = self.activity(brand, period, mode, as_of)
        launches = [e for e in act["events"] if e["event"] == "New Launch"]
        cuts = [e for e in act["events"] if e["event"] == "Price Cut"]
        return {
            "who_is_discounting": {"rivals": disc, "ours": ours_disc["current"], "ours_prev": ours_disc["previous"]},
            "who_gained_share": {
                "subcategory_share": gained.replace({np.nan: None}).to_dict(orient="records"),
                "market_share": [r for r in ms["rivals"] if r["change_pp"] is not None],
                "note": "Share of SubCategory = share of revenue among the 11 tracked brands in our SubCategories; "
                        "market share is the reported metric (6 brands).",
            },
            "who_launched": {"launches": launches, "price_cuts": cuts, "manufacturers": act["manufacturers"],
                             "note": act["note"]},
            "subcategories": subcats,
        }
