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

## Competitor KPIs (always against the selected brand's own competitive set)
- **Price Gap %** = our ASP vs. the external rivals' ASP *in the same SubCategory*. The brand-level figure weights each SubCategory by our revenue there, so a brand is compared like for like (Soap vs Soap), not on product mix.
- **Discount Gap (pp)** = our discount % − rivals' discount %, same weighting. **Competitor Discount %** = the rivals' side of it.
- **Market Share Gap (pp)** = our market share − each external rival's, only where both have data (Dettol, Harpic, Veet vs Ariel, Domex, Lifebuoy).
- **Share of SubCategory** = a brand's share of the revenue of all 11 tracked brands in a SubCategory. It's used for "which competitor gained share" because it exists for every brand, and it's labelled as a within-dataset measure.

## Diagnostics
- Revenue change is split exactly into **Volume + Mix + Price** at SKU level (the residual is 0). MRP never changes, so the price effect is entirely discount-driven.
- **Promotion impact** = discount effect + promo volume effect (change in promo transactions × extra units per promo transaction × previous ASP). In this data promotions add few units, so ending one barely moves revenue: the lost volume and the recovered discount almost cancel.
- Candidate causes (promotions, competitor discounting, competitor events, share shift, stock-outs, ratings and leakage) are each checked with numbers. A cause is "supporting" when it points the same way as the revenue move and, if quantified, explains at least 10% of it.

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

## Q&A layer
- **Numbers only from tools.** The model never sees raw rows; it calls validated tools backed by the KPI engine, so the dashboard and the assistant always agree.
- **Verifier instead of trust.** Every figure in an answer must match a tool number (or a difference / % change of two) at its displayed precision. Dates, labels (Variant 3, Q2, Tier1) and small counts are ignored. One retry; then unsupported sentences are dropped or the offline answer is used.
- **Retrieval for meaning, not numbers.** The knowledge base (KPI definitions, DECISIONS.md, validation caveats, each brand's competitive set) explains *what* a number means; hybrid Chroma (all-MiniLM-L6-v2, local, free) + BM25.
- **One client for Gemini and Ollama** via their OpenAI-compatible endpoints. Gemini's free tier caps requests per model per day, so the client walks a model chain and skips a model whose daily quota is used up instead of retrying.
- **Offline mode** routes by keywords to the same tools and fills templates. It needs no key, is the fallback when the LLM is down, and is the baseline in the evaluation. Its routing was tuned on the evaluation questions, so its score there is not a measure of general ability.
