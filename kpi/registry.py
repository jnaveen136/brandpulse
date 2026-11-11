"""KPI registry: every KPI is defined exactly once, here.

How a KPI is computed
  1. Rows from its `source` table are filtered and grouped.
  2. Additive *base measures* are summed per group (MEASURES below).
  3. The KPI's `formula` turns those sums into the KPI value.

Because ratios (ASP, Margin %, Discount %) are computed from summed measures,
not averaged row by row, every KPI aggregates correctly at any grain: a brand's
ASP is total revenue / total units, never an average of averages.

Growth KPIs (`kind="growth"`) are the % change of a base KPI between the
selected period and its comparison period; the engine computes them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


def _div(a, b, scale=1.0):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, scale * a / b, np.nan)
    return out


# --- Base measures per source: name -> function(df) -> Series to be summed ---
MEASURES: dict[str, dict[str, Callable[[pd.DataFrame], pd.Series]]] = {
    "sales": {
        "Revenue": lambda d: d["Revenue"],
        "Units": lambda d: d["UnitsSold"],
        "Margin": lambda d: d["Margin"],
        "Cost": lambda d: d["Cost"],
        "GrossValue": lambda d: d["GrossValue"],
        "DiscountValue": lambda d: d["DiscountValue"],
        "Txns": lambda d: d["Transactions"],
        "PromoRevenue": lambda d: d["Revenue"].where(d["HasPromo"], 0.0),
        "PromoUnits": lambda d: d["UnitsSold"].where(d["HasPromo"], 0),
        "PromoTxns": lambda d: d["HasPromo"].astype(int),
        "SeasonBaseUnits": lambda d: d["UnitsSold"].where(d["InPromoSeason"] & ~d["HasPromo"], 0),
        "SeasonBaseRevenue": lambda d: d["Revenue"].where(d["InPromoSeason"] & ~d["HasPromo"], 0.0),
        "SeasonBaseTxns": lambda d: (d["InPromoSeason"] & ~d["HasPromo"]).astype(int),
        "Tier1Revenue": lambda d: d["Revenue"].where(d["Tier"] == "Tier1", 0.0),
        # revenue the same units would have earned at each SKU's average price
        # over the filtered rows (added by the engine); basis of Price Index
        "RefRevenue": lambda d: d["RefRevenue"],
    },
    "reviews": {
        "Reviews": lambda d: pd.Series(1, index=d.index),
        "RatingSum": lambda d: d["Rating"],
        "Positive": lambda d: d["IsPositive"].astype(int),
        "Leakage": lambda d: d["IsLeakage"].astype(int),
    },
    "inventory": {
        "Snapshots": lambda d: pd.Series(1, index=d.index),
        "BelowReorder": lambda d: d["BelowReorder"].astype(int),
        "Stock": lambda d: d["StockOnHand"],
    },
    "market_share": {
        "ShareSum": lambda d: d["MarketSharePct"],
        "ShareObs": lambda d: pd.Series(1, index=d.index),
    },
    "marketing": {
        "Spend": lambda d: d["Spend"],
        "Impressions": lambda d: d["Impressions"],
        "Conversions": lambda d: d["Conversions"],
        "ReturnValue": lambda d: d["Spend"] * d["ROI"],  # spend-weighted ROI numerator
        "Campaigns": lambda d: pd.Series(1, index=d.index),
    },
    "events": {
        "Events": lambda d: pd.Series(1, index=d.index),
        "PriceCuts": lambda d: (d["Event"] == "Price Cut").astype(int),
        "Launches": lambda d: (d["Event"] == "New Launch").astype(int),
        "TVCampaigns": lambda d: (d["Event"] == "TV Campaign").astype(int),
        # Competitor Activity Index points: event-type weight x (1 + |price impact| / 10)
        "ActivityPoints": lambda d: d["Event"].map(EVENT_WEIGHTS).fillna(1.0) * (1 + d["PriceImpactPct"].abs() / 10),
    },
}

# A price cut hits our sales directly; a launch adds a new rival product; a TV
# campaign is awareness only. Documented in docs/DECISIONS.md.
EVENT_WEIGHTS = {"Price Cut": 3.0, "New Launch": 2.0, "TV Campaign": 1.0}


@dataclass(frozen=True)
class KPI:
    id: str
    name: str
    group: str
    unit: str  # currency | count | pct | index | rating | score | ratio
    source: str
    description: str
    formula_text: str
    formula: Callable[[pd.DataFrame], np.ndarray] | None = None
    kind: str = "base"  # base | growth
    base: str | None = None  # for growth KPIs
    higher_is_better: bool = True
    scope_note: str = ""
    per_day: bool = False  # KPI value depends on period length -> normalised per 30 days

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "formula"}


def _k(*args, **kw) -> KPI:
    return KPI(*args, **kw)


KPIS: list[KPI] = [
    # ---------------- Revenue ----------------
    _k("revenue", "Total Revenue", "Revenue", "currency", "sales",
       "Money received from sales after discounts.", "SUM(Revenue)", lambda m: m["Revenue"].to_numpy(float)),
    _k("revenue_growth_pct", "Revenue Growth %", "Revenue", "pct", "sales",
       "Change in revenue vs. the comparison period.", "(Revenue - Revenue_prev) / Revenue_prev x 100",
       kind="growth", base="revenue"),
    # ---------------- Volume ----------------
    _k("units", "Units Sold", "Volume", "count", "sales",
       "Number of units sold.", "SUM(UnitsSold)", lambda m: m["Units"].to_numpy(float)),
    _k("unit_growth_pct", "Unit Growth %", "Volume", "pct", "sales",
       "Change in units sold vs. the comparison period.", "(Units - Units_prev) / Units_prev x 100",
       kind="growth", base="units"),
    _k("asp", "Average Selling Price", "Volume", "currency", "sales",
       "Revenue per unit actually sold (after discounts).", "SUM(Revenue) / SUM(UnitsSold)",
       lambda m: _div(m["Revenue"], m["Units"])),
    _k("transactions", "Transactions", "Volume", "count", "sales",
       "Number of sales transactions.", "COUNT(SalesID)", lambda m: m["Txns"].to_numpy(float)),
    # ---------------- Financial ----------------
    _k("margin", "Gross Margin", "Financial", "currency", "sales",
       "Revenue minus product cost.", "SUM(Margin)", lambda m: m["Margin"].to_numpy(float)),
    _k("margin_pct", "Margin %", "Financial", "pct", "sales",
       "Share of revenue kept as margin.", "SUM(Margin) / SUM(Revenue) x 100",
       lambda m: _div(m["Margin"], m["Revenue"], 100)),
    # ---------------- Pricing & promotions ----------------
    _k("discount_pct", "Discount %", "Pricing", "pct", "sales",
       "Average discount off MRP, weighted by units.", "SUM(Units x MRP - Revenue) / SUM(Units x MRP) x 100",
       lambda m: _div(m["DiscountValue"], m["GrossValue"], 100), higher_is_better=False),
    _k("price_index", "Price Index", "Pricing", "index", "sales",
       "Price charged vs. the same SKUs' average price across the selection (100 = average). "
       "Mix-adjusted: compares each SKU with itself.",
       "SUM(Revenue) / SUM(Units x SKU avg price) x 100", lambda m: _div(m["Revenue"], m["RefRevenue"], 100)),
    _k("promo_revenue_share", "Promo Revenue Share", "Promotions", "pct", "sales",
       "Share of revenue sold on promotion.", "SUM(Revenue where Promotion) / SUM(Revenue) x 100",
       lambda m: _div(m["PromoRevenue"], m["Revenue"], 100)),
    _k("promo_lift_pct", "Promo Unit Lift %", "Promotions", "pct", "sales",
       "Extra units per transaction on promotion vs. non-promo transactions in the same promo months.",
       "(PromoUnits/PromoTxns) / (SeasonBaseUnits/SeasonBaseTxns) - 1, x 100",
       lambda m: (_div(_div(m["PromoUnits"], m["PromoTxns"]), _div(m["SeasonBaseUnits"], m["SeasonBaseTxns"])) - 1) * 100),
    _k("promo_revenue_lift_pct", "Promo Revenue Lift %", "Promotions", "pct", "sales",
       "Revenue per transaction on promotion vs. non-promo transactions in the same promo months "
       "(negative = the discount cost more than the extra volume brought in).",
       "(PromoRevenue/PromoTxns) / (SeasonBaseRevenue/SeasonBaseTxns) - 1, x 100",
       lambda m: (_div(_div(m["PromoRevenue"], m["PromoTxns"]), _div(m["SeasonBaseRevenue"], m["SeasonBaseTxns"])) - 1) * 100),
    # ---------------- Distribution ----------------
    _k("tier1_revenue_share", "Premium Retailer Share", "Distribution", "pct", "sales",
       "Share of revenue sold through Tier-1 retailers.", "SUM(Revenue at Tier1) / SUM(Revenue) x 100",
       lambda m: _div(m["Tier1Revenue"], m["Revenue"], 100)),
    # ---------------- Customer ----------------
    _k("avg_rating", "Average Rating", "Customer", "rating", "reviews",
       "Mean review rating (1-5).", "AVG(Rating)", lambda m: _div(m["RatingSum"], m["Reviews"])),
    _k("positive_review_pct", "Positive Reviews %", "Customer", "pct", "reviews",
       "Share of reviews rated 4 or 5.", "COUNT(Rating >= 4) / COUNT(*) x 100",
       lambda m: _div(m["Positive"], m["Reviews"], 100)),
    _k("leakage_complaint_pct", "Leakage Complaints %", "Customer", "pct", "reviews",
       "Share of reviews reporting packaging leakage.", "COUNT(ReviewText = leakage) / COUNT(*) x 100",
       lambda m: _div(m["Leakage"], m["Reviews"], 100), higher_is_better=False),
    _k("reviews", "Review Count", "Customer", "count", "reviews",
       "Number of reviews.", "COUNT(*)", lambda m: m["Reviews"].to_numpy(float)),
    # ---------------- Supply ----------------
    _k("stockout_risk_pct", "Stock-out Risk %", "Supply", "pct", "inventory",
       "Share of stock snapshots below the reorder level.", "COUNT(StockOnHand < ReorderLevel) / COUNT(*) x 100",
       lambda m: _div(m["BelowReorder"], m["Snapshots"], 100), higher_is_better=False),
    _k("avg_stock", "Average Stock on Hand", "Supply", "count", "inventory",
       "Mean units in stock per snapshot.", "AVG(StockOnHand)", lambda m: _div(m["Stock"], m["Snapshots"])),
    # ---------------- Market ----------------
    _k("market_share", "Market Share %", "Market", "pct", "market_share",
       "Average monthly market share in the period. Only 6 of 11 brands have this data, "
       "and shares are measured within those 6 brands.", "AVG(MarketSharePct)",
       lambda m: _div(m["ShareSum"], m["ShareObs"]),
       scope_note="Available for Ariel, Dettol, Domex, Harpic, Lifebuoy, Veet only."),
    # ---------------- Marketing (company level) ----------------
    _k("campaign_spend", "Campaign Spend", "Marketing", "currency", "marketing",
       "Marketing spend on campaigns.", "SUM(Spend)", lambda m: m["Spend"].to_numpy(float),
       higher_is_better=False, scope_note="Company-wide: the data has no brand for campaigns."),
    _k("campaign_roi", "Campaign ROI", "Marketing", "ratio", "marketing",
       "Return per rupee spent, weighted by spend.", "SUM(Spend x ROI) / SUM(Spend)",
       lambda m: _div(m["ReturnValue"], m["Spend"]),
       scope_note="Company-wide: the data has no brand for campaigns."),
    _k("conversion_rate_pct", "Campaign Conversion %", "Marketing", "pct", "marketing",
       "Conversions per impression.", "SUM(Conversions) / SUM(Impressions) x 100",
       lambda m: _div(m["Conversions"], m["Impressions"], 100),
       scope_note="Company-wide: the data has no brand for campaigns."),
    # ---------------- Competitor activity ----------------
    _k("competitor_events", "Competitor Events", "Competitor", "count", "events",
       "Number of competitor events (launches, price cuts, TV campaigns).", "COUNT(*)",
       lambda m: m["Events"].to_numpy(float), higher_is_better=False,
       scope_note="Recorded per manufacturer, not per brand."),
    _k("competitor_activity_index", "Competitor Activity Index", "Competitor", "index", "events",
       "Weighted competitor activity per 30 days. Price cut = 3, launch = 2, TV campaign = 1, "
       "each scaled by (1 + |price impact %| / 10).",
       "SUM(weight x (1 + |PriceImpactPct|/10)) x 30 / days in period",
       lambda m: m["ActivityPoints"].to_numpy(float), higher_is_better=False, per_day=True,
       scope_note="Recorded per manufacturer, not per brand."),
]

REGISTRY: dict[str, KPI] = {k.id: k for k in KPIS}


def get(kpi_id: str) -> KPI:
    try:
        return REGISTRY[kpi_id]
    except KeyError:
        raise KeyError(f"Unknown KPI {kpi_id!r}. Known: {sorted(REGISTRY)}") from None


def catalog() -> pd.DataFrame:
    return pd.DataFrame([k.to_dict() for k in KPIS])
