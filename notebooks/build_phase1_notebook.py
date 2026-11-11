import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []


def md(s):
    C.append(nbf.v4.new_markdown_cell(s.strip()))


def code(s):
    C.append(nbf.v4.new_code_cell(s.strip()))


md("""
# BrandPulse · Phase 1 — Data validity, reusable KPIs and brand-centric EDA

**Dataset:** Brand Intelligence Accelerator v1 (2024-01-01 → 2025-12-30) · 20,440 transactions · 55 SKUs · 11 brands · 3 manufacturers

**Scope:** the 5 Reckitt brands (Dettol, Harpic, Veet, Mortein, Lizol) are the **core brands**. The 6 Unilever and P&G brands (Ariel, Domex, Gillette, Head & Shoulders, Lifebuoy, Lux) are **competitors**.

Every number in this notebook comes from the shared KPI engine (`kpi/engine.py`), the same code the dashboard and the Q&A assistant use.

**Contents**
1. Data validity checks
2. The data model
3. Reusable KPIs and Time Intelligence
4. Univariate view of the transactions
5. Brand-centric period-wise sales
6. Bivariate analysis
7. Multivariate analysis
8. Competitive landscape preview (SubCategory rule)
9. Brand Health Score
10. Key findings
""")

code("""
import sys, json
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import seaborn as sns

from pipeline.build_model import load_model
from pipeline.schema import CORE_BRANDS
from kpi.engine import Engine
from kpi.filters import Filters
from kpi import registry as R, time_intel as T
from kpi.health_score import health_scores

pd.set_option("display.width", 160, "display.max_columns", 30, "display.float_format", "{:,.2f}".format)
eng = Engine(load_model(rebuild=True))
m = eng.m
S = m.sales

# Visual language used in every chart: core brands saturated + solid, competitors muted + dashed
CORE_COLORS = {"Dettol": "#1F6FB2", "Harpic": "#13917A", "Veet": "#C2417F", "Mortein": "#D9741F", "Lizol": "#6B4FBB"}
COMP_COLORS = {"Ariel": "#9AA5B1", "Domex": "#B08F7A", "Gillette": "#8E9C8A", "Head & Shoulders": "#A79AB5",
               "Lifebuoy": "#B5A27A", "Lux": "#9FB0B8"}
BRAND_COLORS = {**CORE_COLORS, **COMP_COLORS}
BRANDS = CORE_BRANDS + sorted(COMP_COLORS)
sns.set_theme(style="whitegrid", rc={"axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 110})
inr = mtick.FuncFormatter(lambda x, _: f"₹{x/1e6:.1f}M" if abs(x) >= 1e6 else f"₹{x/1e3:.0f}K")
print(f"{len(S):,} transactions, {S['Date'].min().date()} → {S['Date'].max().date()}")
""")

# ---------------------------------------------------------------- 1
md("""
## 1. Data validity checks

`pipeline/validate.py` runs 46 checks covering primary keys, nulls, foreign keys, arithmetic identities, value ranges, promotion consistency, calendar coverage and coverage gaps. Each check has a severity: **error** means the data is wrong, **warning** means a gap the dashboard must label, and **info** means a structural fact worth knowing.
""")
code("""
from pipeline.ingest import load_workbook
from pipeline.validate import run_checks, summarize
results = run_checks(load_workbook())
print(summarize(results))
vr = pd.DataFrame([r.__dict__ for r in results]).drop(columns="sample")
vr["result"] = np.where(vr["passed"], "pass", vr["severity"])
vr.groupby(["result"]).size()
""")
code("""
# Everything that is not a clean pass: these become labelled caveats in the dashboard and Q&A
vr[vr["result"] != "pass"][["severity", "check", "sheet", "detail"]].style.hide(axis="index")
""")
code("""
# The checks that matter most for KPI correctness, all passing
vr[vr["check"].isin(["revenue_equals_units_x_price", "margin_equals_price_minus_cost", "price_not_above_mrp",
                     "non_promo_sold_at_mrp", "promo_rows_discounted", "foreign_key", "primary_key_unique"])] \\
  [["check", "sheet", "failing_rows", "detail"]].head(14).style.hide(axis="index")
""")
md("""
**What validation tells us**
- The transaction data is internally consistent: Revenue = Units × Price and Margin = (Price − UnitCost) × Units hold on every row, and every key resolves.
- Promotions are clean. Non-promo rows sell at MRP, and promo rows carry a fixed discount (Summer 10%, Festive 15%).
- Four gaps must be labelled wherever they matter: market share for only 6 brands, marketing with no brand, competitor events recorded per manufacturer, and a missing 2025-12-31.
""")

# ---------------------------------------------------------------- 2
md("## 2. The data model\n\n`pipeline/build_model.py` joins the facts to their dimensions and adds derived columns (`GrossValue`, `DiscountValue`, `HasPromo`, `InPromoSeason`, `IsCore`, `BelowReorder`, `IsLeakage`).")
code("""
pd.DataFrame({t: [len(getattr(m, t)), getattr(m, t).shape[1]] for t in
              ["sales", "reviews", "inventory", "market_share", "marketing", "events", "products", "retailers"]},
             index=["rows", "columns"]).T
""")
code("""
# Every brand has 5 SKUs. SubCategory, not Category, is what the competitor mapping uses (section 8)
pm = m.products.pivot_table(index="Brand", columns="SubCategory", values="ProductID", aggfunc="count", fill_value=0)
pm = pm.loc[BRANDS]
pm.insert(0, "Manufacturer", m.products.groupby("Brand")["Manufacturer"].first().loc[BRANDS])
pm
""")
code("""
# Promotions run in two fixed seasons. That matters for how promo lift is measured (section 6)
pd.crosstab(S["Date"].dt.month, S["Promotion"]).T
""")

# ---------------------------------------------------------------- 3
md("""
## 3. Reusable KPIs and Time Intelligence

Every KPI is declared once in `kpi/registry.py`. Ratios are built from summed measures, so they aggregate correctly at any grain: ASP is total revenue / total units, never an average of averages. Every KPI works with every Time Intelligence preset and comparison mode.
""")
code("""
R.catalog()[["id", "name", "group", "unit", "source", "formula_text"]].style.hide(axis="index")
""")
code("""
# Time Intelligence presets, resolved at the last data date
rows = []
for p in T.PRESETS:
    per, _ = eng.period(p)
    prv = eng.comparison_period(p, "previous")
    yoy = eng.comparison_period(p, "yoy")
    rows.append([p, T.PRESETS[p], per.start.date(), per.end.date(), per.days,
                 f"{prv.start.date()} → {prv.end.date()}", f"{yoy.start.date()} → {yoy.end.date()}"])
pd.DataFrame(rows, columns=["preset", "meaning", "start", "end", "days", "previous period", "same period last year"])
""")
code("""
# One KPI across every preset: Dettol revenue, current vs. same period last year
f = Filters.make(brands="Dettol")
rows = []
for p in T.PRESETS:
    if p == "PY":
        continue
    r = eng.compare("revenue", f, p, "yoy")
    rows.append([p, r["current"], r["previous"], r["delta_pct"], r["comparison_coverage"]])
pd.DataFrame(rows, columns=["preset", "revenue", "revenue SPLY", "YoY %", "SPLY coverage"]).set_index("preset")
""")
code("""
# A scorecard: every core brand, YTD vs. same period last year
kp = ["revenue", "units", "asp", "margin_pct", "discount_pct", "promo_revenue_share", "avg_rating", "stockout_risk_pct"]
rows = {}
for b in CORE_BRANDS:
    sc = eng.scorecard(kp, Filters.make(brands=b), "YTD", "yoy")
    rows[b] = {f"{r['kpi']}": r["current"] for r in sc} | {"revenue YoY %": sc[0]["delta_pct"], "units YoY %": sc[1]["delta_pct"]}
pd.DataFrame(rows).T
""")

# ---------------------------------------------------------------- 4
md("## 4. Univariate view of the transactions")
code("""
fig, ax = plt.subplots(1, 4, figsize=(16, 3.4))
sns.histplot(S["UnitsSold"], bins=40, ax=ax[0], color="#1F6FB2"); ax[0].set_title("Units per transaction")
sns.histplot(S["SellingPrice"], bins=40, ax=ax[1], color="#1F6FB2"); ax[1].set_title("Selling price (₹)")
sns.histplot(S["Revenue"], bins=40, ax=ax[2], color="#1F6FB2"); ax[2].set_title("Revenue per transaction (₹)")
sns.countplot(x=m.reviews["Rating"], ax=ax[3], color="#1F6FB2"); ax[3].set_title("Review ratings")
plt.tight_layout()
S[["UnitsSold", "SellingPrice", "Revenue", "Margin"]].describe().T
""")
md("""
- Selling prices fall on a few MRP points (₹55 to ₹249), so price variation comes mostly from **which SKU** is sold, not from discounting.
- Ratings run only from 2★ to 5★ and are spread almost evenly. There are no 1★ reviews.
""")

# ---------------------------------------------------------------- 5
md("""
## 5. Brand-centric period-wise sales

This is the core of the EDA: how each brand's sales move over time, with the 5 core brands shown solid and in colour, and competitors dashed and muted.
""")
code("""
ts = eng.timeseries("revenue", "M", None, "ALL", by="Brand")
fig, ax = plt.subplots(figsize=(15, 5.5))
for b in BRANDS:
    d = ts[ts["Brand"] == b]
    core = b in CORE_BRANDS
    ax.plot(d["bucket"], d["value"], label=b, color=BRAND_COLORS[b], lw=2.4 if core else 1.3,
            ls="-" if core else "--", alpha=1 if core else 0.85)
ax.yaxis.set_major_formatter(inr); ax.set_title("Monthly revenue by brand (core = solid, competitor = dashed)")
for start, end, lab in [("2024-03-01", "2024-05-31", "Summer"), ("2024-09-01", "2024-11-30", "Festive"),
                         ("2025-03-01", "2025-05-31", "Summer"), ("2025-09-01", "2025-11-30", "Festive")]:
    ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color="#F2C14E", alpha=0.10)
ax.legend(ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
plt.tight_layout()
""")
code("""
# Year totals and YoY growth per brand (same calendar days: 1 Jan - 30 Dec)
rows = []
for b in BRANDS:
    r = eng.compare("revenue", Filters.make(brands=b), "YTD", "yoy")
    u = eng.compare("units", Filters.make(brands=b), "YTD", "yoy")
    rows.append([b, "Core" if b in CORE_BRANDS else "Competitor", r["previous"], r["current"], r["delta_pct"], u["delta_pct"]])
yoy = pd.DataFrame(rows, columns=["Brand", "Type", "Revenue 2024", "Revenue 2025", "Revenue YoY %", "Units YoY %"]).set_index("Brand")
yoy.sort_values("Revenue 2025", ascending=False)
""")
code("""
# Month-by-month YoY growth heatmap: where in the year each brand grew or shrank
mt = eng.timeseries("revenue", "M", None, "ALL", by="Brand")
mt["year"], mt["month"] = mt["bucket"].dt.year, mt["bucket"].dt.month
pv = mt.pivot_table(index=["Brand", "month"], columns="year", values="value").reset_index()
pv["yoy"] = 100 * (pv[2025] / pv[2024] - 1)
heat = pv.pivot(index="Brand", columns="month", values="yoy").loc[BRANDS]
heat.columns = [pd.Timestamp(2025, c, 1).strftime("%b") for c in heat.columns]
fig, ax = plt.subplots(figsize=(13, 5))
sns.heatmap(heat, annot=True, fmt=".0f", cmap="RdBu", center=0, vmin=-40, vmax=40, cbar_kws={"label": "YoY %"}, ax=ax)
ax.axhline(5, color="black", lw=1.5); ax.set_title("Monthly revenue YoY % (2025 vs 2024). Core brands above the line"); ax.set_ylabel("")
plt.tight_layout()
""")
code("""
# Quarterly revenue per core brand, with each quarter's share of the brand's year
q = eng.timeseries("revenue", "Q", Filters.make(brands=CORE_BRANDS), "ALL", by="Brand")
q["Quarter"] = q["bucket"].dt.year.astype(str) + "-Q" + q["bucket"].dt.quarter.astype(str)
qp = q.pivot(index="Brand", columns="Quarter", values="value").loc[CORE_BRANDS]
qp
""")
code("""
# Seasonality index: each month's revenue vs. the brand's average month (100 = average), both years combined
mt["month_name"] = mt["bucket"].dt.strftime("%b")
si = mt.groupby(["Brand", "month"])["value"].sum().unstack()
si = 100 * si.div(si.mean(axis=1), axis=0)
si.columns = [pd.Timestamp(2025, c, 1).strftime("%b") for c in si.columns]
fig, ax = plt.subplots(figsize=(13, 4.5))
sns.heatmap(si.loc[BRANDS], annot=True, fmt=".0f", cmap="PuOr_r", center=100, ax=ax, cbar_kws={"label": "index"})
ax.axhline(5, color="black", lw=1.5); ax.set_title("Seasonality index by brand (100 = the brand's average month)"); ax.set_ylabel("")
plt.tight_layout()
""")
code("""
# Weekly revenue for the core brands with a 4-week rolling mean: the short-term noise behind the monthly trend
w = eng.timeseries("revenue", "W", Filters.make(brands=CORE_BRANDS), "ALL", by="Brand")
w = w[~w["partial"]]
fig, axes = plt.subplots(1, 5, figsize=(18, 3.2), sharey=True)
for ax, b in zip(axes, CORE_BRANDS):
    d = w[w["Brand"] == b].set_index("bucket")["value"]
    ax.plot(d.index, d, color=CORE_COLORS[b], alpha=0.3, lw=1)
    ax.plot(d.index, d.rolling(4).mean(), color=CORE_COLORS[b], lw=2)
    ax.set_title(b); ax.yaxis.set_major_formatter(inr); ax.tick_params(axis="x", rotation=45)
plt.suptitle("Weekly revenue (thin) and 4-week rolling mean (thick)", y=1.04); plt.tight_layout()
""")
code("""
# Day-of-week pattern
dow = S.assign(dow=S["Date"].dt.day_name()).groupby(["dow", "IsCore"])["Revenue"].sum().unstack()
dow = dow.loc[["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]]
(100 * dow / dow.mean()).rename(columns={True: "Core index", False: "Competitor index"}).round(1)
""")

# ---------------------------------------------------------------- 6
md("## 6. Bivariate analysis")
code("""
# Brand x Retailer: where each core brand's revenue comes from (share of the brand's revenue)
br = eng.breakdown("revenue", ["Brand", "Retailer"], Filters.make(brands=CORE_BRANDS), "YTD")
brp = br.pivot(index="Brand", columns="Retailer", values="value").loc[CORE_BRANDS]
brp = 100 * brp.div(brp.sum(axis=1), axis=0)
tiers = m.retailers.set_index("Retailer")["Tier"]
brp = brp[sorted(brp.columns, key=lambda r: (tiers[r], r))]
fig, ax = plt.subplots(figsize=(13, 3.6))
sns.heatmap(brp, annot=True, fmt=".1f", cmap="Blues", ax=ax, cbar_kws={"label": "% of brand revenue"})
ax.set_xticklabels([f"{r}\\n({tiers[r]})" for r in brp.columns], rotation=0, fontsize=8)
ax.set_title("2025 revenue mix by retailer, per core brand"); ax.set_ylabel(""); ax.set_xlabel("")
plt.tight_layout()
""")
code("""
# Brand x Region and Brand x Channel (share of the brand's 2025 revenue)
fig, ax = plt.subplots(1, 2, figsize=(15, 4.6))
for a, dim, cmap in [(ax[0], "Region", "Greens"), (ax[1], "Channel", "Purples")]:
    b = eng.breakdown("revenue", ["Brand", dim], None, "YTD").pivot(index="Brand", columns=dim, values="value").loc[BRANDS]
    sns.heatmap(100 * b.div(b.sum(axis=1), axis=0), annot=True, fmt=".1f", cmap=cmap, ax=a, cbar=False)
    a.axhline(5, color="black", lw=1.5); a.set_title(f"% of brand revenue by {dim}"); a.set_ylabel("")
plt.tight_layout()
""")
code("""
# Price vs. volume at SKU level: does a higher price mean fewer units?
sku = S[S["Date"].dt.year == 2025].groupby(["ProductID", "Brand", "SubCategory", "IsCore"]).agg(
    Revenue=("Revenue", "sum"), Units=("UnitsSold", "sum"), MRP=("MRP", "first")).reset_index()
sku["ASP"] = sku["Revenue"] / sku["Units"]
fig, ax = plt.subplots(figsize=(10, 5))
for core, mk in [(True, "o"), (False, "^")]:
    d = sku[sku["IsCore"] == core]
    ax.scatter(d["ASP"], d["Units"], c=[BRAND_COLORS[b] for b in d["Brand"]], marker=mk, s=70,
               alpha=0.9 if core else 0.6, edgecolor="white", label="Core SKU" if core else "Competitor SKU")
ax.set_xlabel("ASP (₹)"); ax.set_ylabel("Units sold, 2025"); ax.set_title("Price vs. volume per SKU"); ax.legend()
print("Spearman correlation, ASP vs units:", round(sku[["ASP", "Units"]].corr("spearman").iloc[0, 1], 3))
""")
code("""
# Promotion effect, measured inside promo months only (promo vs. non-promo rows in the same months)
rows = []
for b in BRANDS:
    f = Filters.make(brands=b)
    rows.append([b, eng.value("promo_revenue_share", f, "ALL"), eng.value("promo_lift_pct", f, "ALL"),
                 eng.value("promo_revenue_lift_pct", f, "ALL")])
promo = pd.DataFrame(rows, columns=["Brand", "Promo revenue share %", "Unit lift % per txn", "Revenue lift % per txn"]).set_index("Brand")
by_promo = S[S["InPromoSeason"]].groupby("Promotion")[["UnitsSold", "Revenue"]].mean()
display(by_promo.rename(columns={"UnitsSold": "avg units / txn", "Revenue": "avg revenue / txn"}))
promo
""")
code("""
# Discount depth vs. units per transaction, by retailer tier
fig, ax = plt.subplots(figsize=(9, 4))
sns.boxplot(data=S[S["InPromoSeason"]], x="Promotion", y="UnitsSold", hue="Tier", ax=ax, palette=["#1F6FB2", "#9AA5B1"])
ax.set_title("Units per transaction in promo months: promotion type x retailer tier")
plt.tight_layout()
""")
code("""
# Rating vs. growth: do better-rated brands grow faster?
rt = pd.DataFrame({b: {"avg_rating": eng.value("avg_rating", Filters.make(brands=b), "YTD"),
                       "leakage %": eng.value("leakage_complaint_pct", Filters.make(brands=b), "YTD"),
                       "revenue YoY %": yoy.loc[b, "Revenue YoY %"]} for b in BRANDS}).T
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.scatter(rt["avg_rating"], rt["revenue YoY %"], c=[BRAND_COLORS[b] for b in rt.index], s=120)
for b, r in rt.iterrows():
    ax.annotate(b, (r["avg_rating"], r["revenue YoY %"]), xytext=(5, 4), textcoords="offset points", fontsize=9,
                fontweight="bold" if b in CORE_BRANDS else "normal")
ax.axhline(0, color="grey", lw=0.8); ax.set_xlabel("Average rating 2025"); ax.set_ylabel("Revenue YoY %")
ax.set_title("Rating vs. revenue growth by brand")
rt.round(2)
""")
code("""
# Margin % vs. ASP per brand
fin = pd.DataFrame({b: {"ASP": eng.value("asp", Filters.make(brands=b), "YTD"),
                        "Margin %": eng.value("margin_pct", Filters.make(brands=b), "YTD"),
                        "Revenue": eng.value("revenue", Filters.make(brands=b), "YTD")} for b in BRANDS}).T
fin.sort_values("Margin %", ascending=False)
""")

# ---------------------------------------------------------------- 7
md("""
## 7. Multivariate analysis

Built on a **SKU × month panel** (55 SKUs × 24 months), so each row is one product in one month with all of its KPIs together.
""")
code("""
S2 = S.assign(month=S["Date"].dt.to_period("M"))
panel = S2.groupby(["ProductID", "Brand", "IsCore", "SubCategory", "month"]).agg(
    Revenue=("Revenue", "sum"), Units=("UnitsSold", "sum"), Gross=("GrossValue", "sum"), Disc=("DiscountValue", "sum"),
    Margin=("Margin", "sum"), PromoRev=("Revenue", lambda s: s[S2.loc[s.index, "HasPromo"]].sum()),
    T1=("Revenue", lambda s: s[S2.loc[s.index, "Tier"] == "Tier1"].sum())).reset_index()
panel["ASP"] = panel["Revenue"] / panel["Units"]
panel["Discount %"] = 100 * panel["Disc"] / panel["Gross"]
panel["Margin %"] = 100 * panel["Margin"] / panel["Revenue"]
panel["Promo share %"] = 100 * panel["PromoRev"] / panel["Revenue"]
panel["Tier1 share %"] = 100 * panel["T1"] / panel["Revenue"]
rv = m.reviews.assign(month=m.reviews["Date"].dt.to_period("M")).groupby(["ProductID", "month"])["Rating"].mean().rename("Rating")
iv = m.inventory.assign(month=m.inventory["Date"].dt.to_period("M")).groupby(["ProductID", "month"]).agg(
    **{"Stock-out risk %": ("BelowReorder", lambda s: 100 * s.mean()), "Avg stock": ("StockOnHand", "mean")})
panel = panel.join(rv, on=["ProductID", "month"]).join(iv, on=["ProductID", "month"])
feats = ["Revenue", "Units", "ASP", "Discount %", "Margin %", "Promo share %", "Tier1 share %", "Rating", "Stock-out risk %", "Avg stock"]
print(panel.shape)
fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(panel[feats].corr("spearman"), annot=True, fmt=".2f", cmap="RdBu", center=0, vmin=-1, vmax=1, ax=ax, square=True)
ax.set_title("Spearman correlation across the SKU × month panel"); plt.tight_layout()
""")
code("""
# Same correlations, but within each SKU (each SKU's monthly deviations from its own average):
# removes the "expensive SKUs sell fewer units" effect and shows what moves together over time
within = panel.copy()
within[feats] = within.groupby("ProductID")[feats].transform(lambda s: s - s.mean())
fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(within[feats].corr(), annot=True, fmt=".2f", cmap="RdBu", center=0, vmin=-1, vmax=1, ax=ax, square=True)
ax.set_title("Within-SKU correlation (monthly deviations from each SKU's mean)"); plt.tight_layout()
""")
code("""
# Explaining monthly units per SKU with several factors at once (within-SKU OLS with standardised inputs).
# Coefficients = change in units for a 1-standard-deviation change in each factor, holding the others fixed.
X_cols = ["Discount %", "Tier1 share %", "Rating", "Stock-out risk %"]
d = within.dropna(subset=X_cols + ["Units"])
X = (d[X_cols] - d[X_cols].mean()) / d[X_cols].std()
X.insert(0, "const", 1.0)
coef, *_ = np.linalg.lstsq(X.to_numpy(), d["Units"].to_numpy(), rcond=None)
pred = X.to_numpy() @ coef
r2 = 1 - ((d["Units"] - pred) ** 2).sum() / ((d["Units"] - d["Units"].mean()) ** 2).sum()
print(f"Within-SKU R² = {r2:.3f} on {len(d):,} SKU-months")
pd.Series(coef[1:], index=X_cols, name="units per 1 SD").round(1).to_frame()
""")
code("""
# Brand x SubCategory x Retailer tier: 2025 revenue for the core brands
cube = eng.breakdown("revenue", ["Brand", "SubCategory", "Tier"], Filters.make(brands=CORE_BRANDS), "YTD")
cp = cube.pivot_table(index=["Brand", "SubCategory"], columns="Tier", values="value", fill_value=0)
cp["Tier1 %"] = 100 * cp["Tier1"] / cp.sum(axis=1)
cp
""")
code("""
# Small multiples: monthly revenue per core brand split by retailer channel
ch = eng.timeseries("revenue", "M", Filters.make(brands=CORE_BRANDS), "ALL", by=["Brand", "Channel"])
g = sns.relplot(data=ch, x="bucket", y="value", hue="Channel", col="Brand", kind="line", col_wrap=5, height=2.8, aspect=1.2,
                palette=["#1F6FB2", "#13917A", "#D9741F"], facet_kws={"sharey": False})
g.set_axis_labels("", "Revenue"); g.set_titles("{col_name}")
for ax in g.axes.flat:
    ax.yaxis.set_major_formatter(inr); ax.tick_params(axis="x", rotation=45)
""")

# ---------------------------------------------------------------- 8
md("""
## 8. Competitive landscape preview (SubCategory rule)

A core variant competes with every SKU in the **same SubCategory**, and Category is ignored. Phase 2 builds the full 3-tier mapping: same brand, other Reckitt brands, external. This preview counts, for each core brand, how many of its 5 variants face each external brand.
""")
code("""
P = m.products
ext = P[~P["IsCore"]]
rows = []
for b in CORE_BRANDS:
    for _, v in P[P["Brand"] == b].iterrows():
        rivals = ext[ext["SubCategory"] == v["SubCategory"]]["Brand"].unique()
        for r in rivals:
            rows.append([b, v["ProductID"], r])
ov = pd.DataFrame(rows, columns=["Core brand", "Variant", "Rival"]).drop_duplicates()
overlap = ov.groupby(["Core brand", "Rival"])["Variant"].nunique().unstack(fill_value=0).loc[CORE_BRANDS]
fig, ax = plt.subplots(figsize=(9, 3.6))
sns.heatmap(overlap, annot=True, fmt="d", cmap="Oranges", vmin=0, vmax=5, ax=ax, cbar_kws={"label": "variants overlapped (of 5)"})
ax.set_title("How many of each core brand's 5 variants face each external brand"); ax.set_ylabel("")
plt.tight_layout()
""")
code("""
# Head to head at SubCategory level, 2025: each core brand's ASP vs. external rivals' ASP in the same SubCategory
rows = []
for b in CORE_BRANDS:
    for sc in P[P["Brand"] == b]["SubCategory"].unique():
        own = eng.value("asp", Filters.make(brands=b, subcategories=sc), "YTD")
        rv_ = eng.value("asp", Filters.make(brands=list(ext["Brand"].unique()), subcategories=sc), "YTD")
        rd = eng.value("discount_pct", Filters.make(brands=list(ext["Brand"].unique()), subcategories=sc), "YTD")
        rows.append([b, sc, own, rv_, 100 * (own / rv_ - 1), eng.value("discount_pct", Filters.make(brands=b, subcategories=sc), "YTD"), rd])
pd.DataFrame(rows, columns=["Brand", "SubCategory", "Our ASP", "Rival ASP", "Price gap %", "Our discount %", "Rival discount %"]).set_index(["Brand", "SubCategory"])
""")
code("""
# Market share (6 brands with data), monthly
ms = m.market_share.pivot(index="Date", columns="Brand", values="MarketSharePct")
fig, ax = plt.subplots(figsize=(13, 4))
for b in ms.columns:
    core = b in CORE_BRANDS
    ax.plot(ms.index, ms[b], color=BRAND_COLORS[b], lw=2.4 if core else 1.3, ls="-" if core else "--", label=b)
ax.set_title("Market share % (measured within these 6 brands; Lizol and Mortein have no data)")
ax.legend(ncol=6, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1)); plt.tight_layout()
share_change = pd.DataFrame({b: eng.compare("market_share", Filters.make(brands=b), "YTD", "yoy") for b in ms.columns}).T[["current", "previous", "delta"]]
share_change.columns = ["2025 avg share", "2024 avg share", "change (pp)"]
share_change.astype(float).sort_values("change (pp)", ascending=False)
""")
code("""
# Competitor events by manufacturer and type
ev = m.events.assign(year=m.events["Date"].dt.year)
pd.crosstab([ev["Competitor"], ev["year"]], ev["Event"], margins=True)
""")

# ---------------------------------------------------------------- 9
md("""
## 9. Brand Health Score

| Component | Measure | Weight |
|---|---|---|
| Growth | Revenue YoY % | 30% |
| Margin | Margin % | 25% |
| Rating | Average rating | 25% |
| Position | Market share change in pp (**real**, 6 brands) or Premium Retailer Share change in pp (**proxy**, 5 brands) | 20% |

Each component becomes a z-score, then a 0–100 score (50 = average brand). **The position component is standardised within its own source group**, so the real-share and proxy brands are never ranked on each other's scales.
""")
code("""
hs = health_scores(eng, "YTD", "yoy")
cols = ["IsCore", "growth", "margin", "rating", "position", "position_source",
        "growth_score", "margin_score", "rating_score", "position_score", "health_score", "rank"]
hs[cols].style.format(precision=2).background_gradient(subset=["health_score"], cmap="RdYlGn", vmin=20, vmax=80)
""")
code("""
fig, ax = plt.subplots(figsize=(11, 4.5))
order = hs.index.tolist()
left = np.zeros(len(order))
from kpi.health_score import WEIGHTS
for comp, col in zip(WEIGHTS, ["#1F6FB2", "#13917A", "#D9A21F", "#C2417F"]):
    vals = (hs[f"{comp}_score"] * WEIGHTS[comp]).to_numpy()
    ax.barh(order, vals, left=left, color=col, label=f"{comp} ({int(WEIGHTS[comp]*100)}%)")
    left += vals
for i, b in enumerate(order):
    ax.text(left[i] + 0.8, i, f"{left[i]:.0f}" + ("  (proxy)" if hs.loc[b, "position_source"] == "proxy" else ""), va="center", fontsize=9)
ax.invert_yaxis(); ax.set_xlim(0, 100); ax.legend(ncol=4, loc="lower right", fontsize=8)
for t in ax.get_yticklabels():
    t.set_fontweight("bold" if t.get_text() in CORE_BRANDS else "normal")
ax.set_title("Brand Health Score 2025 and what makes it up (core brands in bold)"); plt.tight_layout()
""")

# ---------------------------------------------------------------- 10
md("## 10. Key findings\n\nGenerated from the numbers above, so they stay correct if the data changes.")
code("""
core = yoy[yoy["Type"] == "Core"]
comp = yoy[yoy["Type"] == "Competitor"]
best_hs = hs[hs["IsCore"]].iloc[0]; worst_hs = hs[hs["IsCore"]].iloc[-1]
r_core = eng.compare("revenue", Filters.make(brands=CORE_BRANDS), "YTD", "yoy")
r_comp = eng.compare("revenue", Filters.make(brands=list(COMP_COLORS)), "YTD", "yoy")
avg_lift = eng.value("promo_lift_pct", None, "ALL"); avg_rev_lift = eng.value("promo_revenue_lift_pct", None, "ALL")
findings = [
    f"Core brands' 2025 revenue changed {r_core['delta_pct']:+.1f}% YoY, vs {r_comp['delta_pct']:+.1f}% for the competitor brands.",
    "Growing core brands: " + (", ".join(f"{b} ({v:+.1f}%)" for b, v in core["Revenue YoY %"].items() if v > 0) or "none")
      + ". Shrinking: " + ", ".join(f"{b} ({v:+.1f}%)" for b, v in core["Revenue YoY %"].items() if v <= 0) + ".",
    f"Fastest-growing competitor: {comp['Revenue YoY %'].idxmax()} ({comp['Revenue YoY %'].max():+.1f}%).",
    f"Promotions barely move volume: units per promo transaction are {avg_lift:+.1f}% vs non-promo rows in the same months, "
      f"while the 10-15% discount makes revenue per promo transaction {avg_rev_lift:+.1f}%. Promotions cost revenue in this data.",
    (lambda lk: f"Packaging leakage complaints appear only for Dettol: {int(lk.sum())} reviews, all in "
      f"{', '.join(map(str, lk.index))}, spread across all 5 Dettol SKUs (worst: Liquid). A contained quality incident, not a "
      f"steady pattern.")(m.reviews[m.reviews['IsLeakage']].groupby(m.reviews['Date'].dt.to_period('Q')).size()),
    f"Highest core Health Score: {best_hs.name} ({best_hs['health_score']:.0f}); lowest: {worst_hs.name} ({worst_hs['health_score']:.0f}).",
    f"Market share 2025 vs 2024 (pp): " + ", ".join(f"{b} {v:+.2f}" for b, v in share_change['change (pp)'].astype(float).items()) + ".",
    f"Lizol and Mortein have no market-share data; their Health Score position uses the labelled Premium Retailer Share proxy.",
    f"Campaign spend and ROI cannot be split by brand (no Brand column); competitor events are only known per manufacturer.",
]
for i, f_ in enumerate(findings, 1):
    print(f"{i}. {f_}")
""")
md("""
**Next: Phase 2** builds the per-variant 3-tier competitor mapping, the competitor KPIs (Price Gap, Discount Gap, Market Share Gap, Competitor Activity Index) for a selected core brand, and the Diagnostics engine that explains why revenue moved.
""")

nb["cells"] = C
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, str(__import__("pathlib").Path(__file__).with_name("phase1_eda.ipynb")))
print("written", len(C), "cells")
