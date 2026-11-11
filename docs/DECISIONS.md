# Decisions and data caveats

Short record of every judgement call, so anyone presenting the dashboard can explain it.

## Scope
- **Core brands** are Reckitt's 5: Dettol, Harpic, Veet, Mortein, Lizol. The 6 Unilever and P&G brands (Ariel, Domex, Gillette, Head & Shoulders, Lifebuoy, Lux) are competitors only: they appear as rivals and can't be selected as the focus brand.
- **No all-company totals.** The dashboard always centres on one core brand. Revenue summed across all 11 brands has no business meaning and is not shown.
- **Revenue vs Target** is dropped, as agreed with the mentor.

## Competitor mapping
- A core variant competes with every SKU in the **same SubCategory**; Category is ignored. Category labels are not consistent within a brand (all 11 brands have SKUs in several Categories), and the confirmed example (Dettol/Lizol Liquid vs. Domex, Ariel, Head & Shoulders Liquid) only works on SubCategory.
- Rivals are shown in **3 tiers**: same brand's other variants, other Reckitt brands, external competitors.
- **Closest rival** counts external competitors only: the brand present in the most of the core brand's variants.

## KPI definitions
- Ratios (ASP, Margin %, Discount %, Price Index) are built from summed measures, never averages of row-level ratios.
- **Promo lift** compares promo and non-promo transactions inside the same promo months (Summer Mar–May, Festive Sep–Nov), so seasonality isn't counted as a promotion effect.
- **Price Index** compares each SKU with its own average price across the selection (mix-adjusted), so a retailer that sells more expensive SKUs isn't wrongly labelled "premium priced".
- **Competitor Activity Index** = Σ event weight × (1 + |price impact %| / 10), per 30 days. Weights: Price Cut 3, New Launch 2, TV Campaign 1. A price cut hits our sales directly; a launch adds a rival product; a TV campaign is awareness only.
- **Market share** for a period is the average of the monthly shares of the months that overlap it. The data is monthly, so windows shorter than a month (WTD, R7) show the month's value and no change.

## Brand Health Score
- Components: revenue growth (30%), margin % (25%), average rating (25%), market position change (20%).
- Market position uses the real market-share change where it exists (6 brands). For Lizol, Mortein, Gillette, Head & Shoulders and Lux it uses the change in **Premium Retailer Share** (share of revenue through Tier-1 retailers), always labelled "proxy".
- Rejected proxy: "revenue share among the 11 brands". Tested against the 6 brands with real share, it got the trend direction wrong for 5 of 6, because the 11 brands are a closed, zero-sum set.
- Each component → z-score → 0–100 via the normal CDF (50 = average brand). The position component is standardised **within its source group** (real vs. proxy), since the two are on different scales.

## Data caveats (shown in the UI where relevant)
| Caveat | Effect |
|---|---|
| Market share covers 6 of 11 brands, and those 6 add up to ~100% | Share is "within this set of brands"; Lizol and Mortein show the proxy |
| Fact_Marketing has no Brand column | Campaign spend and ROI are company-wide only |
| Competitor events are per manufacturer; SC Johnson has events but no products | Events are shown on timelines for the rival's manufacturer, not attributed to a brand |
| 2025-12-31 is missing | YTD 2025 runs to 30 Dec and is compared with 1 Jan–30 Dec 2024 |
| ReviewText is 3 fixed phrases tied to rating | Sentiment = rating; only the leakage complaint is extra signal |
| Retailer names are global chains with ₹ prices | Data is synthetic; treat retailers as labels |
