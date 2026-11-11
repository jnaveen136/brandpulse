"""Data validity checks.

Each check returns a CheckResult with a severity:
  error   - the data is wrong; KPIs built on it can't be trusted
  warning - the data is usable but has a gap the dashboard must label
  info    - a structural fact worth knowing (not a defect)

The results are written to reports/data_quality.json and .md, shown in the
Streamlit workbench, and fed to the Q&A layer so it can quote data caveats.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import CORE_BRANDS, CORE_MANUFACTURER, FOREIGN_KEYS, SHEETS

TOL = 0.01  # currency rounding tolerance


@dataclass
class CheckResult:
    check: str
    sheet: str
    severity: str  # error | warning | info
    passed: bool
    failing_rows: int
    detail: str
    sample: list = field(default_factory=list)


def _sample(df: pd.DataFrame, n: int = 5) -> list:
    return json.loads(df.head(n).to_json(orient="records", date_format="iso"))


def run_checks(t: dict[str, pd.DataFrame]) -> list[CheckResult]:
    out: list[CheckResult] = []

    def add(check, sheet, severity, bad: pd.DataFrame | None, detail, passed=None):
        n = 0 if bad is None else len(bad)
        out.append(CheckResult(
            check, sheet, severity, n == 0 if passed is None else passed, n, detail,
            [] if bad is None else _sample(bad),
        ))

    # 1. Primary keys and nulls
    for sheet, spec in SHEETS.items():
        df = t[sheet]
        pk = spec["primary_key"]
        if pk:
            dup = df[df.duplicated(pk, keep=False)]
            add("primary_key_unique", sheet, "error", dup, f"{'+'.join(pk)} must be unique")
        nullable = set(spec.get("nullable", []))
        cols = [c for c in df.columns if c not in nullable]
        nulls = df[df[cols].isna().any(axis=1)]
        add("no_unexpected_nulls", sheet, "error", nulls, f"No nulls outside {sorted(nullable) or 'none'}")

    # 2. Foreign keys
    for child, ccol, parent, pcol in FOREIGN_KEYS:
        orphan = t[child][~t[child][ccol].isin(set(t[parent][pcol]))]
        add("foreign_key", child, "error", orphan, f"{child}.{ccol} must exist in {parent}.{pcol}")

    sales = t["Fact_Sales"].merge(t["Dim_Product"][["ProductID", "MRP", "UnitCost"]], on="ProductID")

    # 3. Arithmetic identities
    bad = sales[(sales["Revenue"] - sales["UnitsSold"] * sales["SellingPrice"]).abs() > TOL]
    add("revenue_equals_units_x_price", "Fact_Sales", "error", bad, "Revenue = UnitsSold x SellingPrice")
    bad = sales[(sales["Margin"] - (sales["SellingPrice"] - sales["UnitCost"]) * sales["UnitsSold"]).abs() > TOL]
    add("margin_equals_price_minus_cost", "Fact_Sales", "error", bad, "Margin = (SellingPrice - UnitCost) x UnitsSold")

    # 4. Value ranges
    add("units_positive", "Fact_Sales", "error", sales[sales["UnitsSold"] <= 0], "UnitsSold > 0")
    add("revenue_positive", "Fact_Sales", "error", sales[sales["Revenue"] <= 0], "Revenue > 0")
    add("price_not_above_mrp", "Fact_Sales", "error", sales[sales["SellingPrice"] > sales["MRP"] + TOL],
        "SellingPrice <= MRP")
    add("margin_positive", "Fact_Sales", "warning", sales[sales["Margin"] <= 0], "Margin > 0 (loss-making rows)")
    p = t["Dim_Product"]
    add("cost_below_mrp", "Dim_Product", "error", p[p["UnitCost"] >= p["MRP"]], "UnitCost < MRP")
    r = t["Fact_Reviews"]
    add("rating_in_1_to_5", "Fact_Reviews", "error", r[~r["Rating"].between(1, 5)], "Rating between 1 and 5")
    inv = t["Fact_Inventory"]
    add("stock_non_negative", "Fact_Inventory", "error", inv[inv["StockOnHand"] < 0], "StockOnHand >= 0")
    ms = t["Fact_MarketShare"]
    add("share_in_0_100", "Fact_MarketShare", "error", ms[~ms["MarketSharePct"].between(0, 100)],
        "MarketSharePct between 0 and 100")

    # 5. Promotion consistency: promo rows should be discounted, non-promo rows at MRP
    disc = 1 - sales["SellingPrice"] / sales["MRP"]
    bad = sales[sales["Promotion"].isna() & (disc > 0.001)]
    add("non_promo_sold_at_mrp", "Fact_Sales", "warning", bad, "Rows without a promotion should sell at MRP")
    bad = sales[sales["Promotion"].notna() & (disc <= 0.001)]
    add("promo_rows_discounted", "Fact_Sales", "warning", bad, "Promotion rows should carry a discount")

    # 6. Calendar coverage
    dd = t["Dim_Date"]
    full = pd.date_range(dd["Date"].min(), f"{dd['Date'].max().year}-12-31", freq="D")
    gaps = sorted(set(full) - set(dd["Date"]))
    out.append(CheckResult(
        "calendar_complete", "Dim_Date", "warning", not gaps, len(gaps),
        "Calendar should cover every day of each year. Missing: "
        + (", ".join(d.strftime("%Y-%m-%d") for d in gaps) or "none")
        + ". Year-end comparisons treat the last year as ending one day early.",
    ))
    sales_days = sales["Date"].nunique()
    out.append(CheckResult(
        "sales_every_day", "Fact_Sales", "info", sales_days == len(dd), len(dd) - sales_days,
        f"Sales exist on {sales_days} of {len(dd)} calendar days",
    ))

    # 7. Coverage gaps the dashboard must label
    brands = set(p["Brand"])
    no_share = sorted(brands - set(ms["Brand"]))
    out.append(CheckResult(
        "market_share_coverage", "Fact_MarketShare", "warning", not no_share, len(no_share),
        f"Market share exists for {len(brands) - len(no_share)} of {len(brands)} brands. Missing: {', '.join(no_share)}. "
        f"Core brands without share: {', '.join(b for b in no_share if b in CORE_BRANDS) or 'none'}.",
    ))
    share_total = ms.groupby("Date")["MarketSharePct"].sum()
    out.append(CheckResult(
        "market_share_is_within_tracked_set", "Fact_MarketShare", "info", True, 0,
        f"The {ms['Brand'].nunique()} brands' shares add up to {share_total.min():.1f}-{share_total.max():.1f}% each month, "
        "so the share is measured within this set of brands, not the whole market.",
    ))
    out.append(CheckResult(
        "marketing_has_no_brand", "Fact_Marketing", "warning", False, len(t["Fact_Marketing"]),
        "Fact_Marketing has no Brand column: campaign spend and ROI can only be reported for the company as a whole.",
    ))
    ev = t["Fact_CompetitorEvents"]
    known = set(p["Manufacturer"])
    unknown = sorted(set(ev["Competitor"]) - known)
    out.append(CheckResult(
        "competitor_events_are_manufacturer_level", "Fact_CompetitorEvents", "warning", False, len(ev),
        f"Events are recorded per manufacturer ({', '.join(sorted(set(ev['Competitor'])))}), not per brand. "
        f"{', '.join(unknown) or 'None'} has events but no products in the data.",
    ))
    cats = p.groupby("Brand")["Category"].nunique()
    out.append(CheckResult(
        "category_not_brand_consistent", "Dim_Product", "info", False, int((cats > 1).sum()),
        f"{int((cats > 1).sum())} of {len(cats)} brands have SKUs in more than one Category, so competitors are "
        "matched on SubCategory only (see docs/DECISIONS.md).",
    ))
    rt = r.groupby("Rating")["ReviewText"].unique()
    out.append(CheckResult(
        "review_text_templated", "Fact_Reviews", "info", False, int(r["ReviewText"].nunique()),
        "ReviewText has only " + str(r["ReviewText"].nunique()) + " fixed phrases tied to rating: "
        + "; ".join(f"{k}★: {', '.join(v)}" for k, v in rt.items())
        + ". Only the leakage complaint adds information beyond the rating.",
    ))
    core_mfr = p[p["Brand"].isin(CORE_BRANDS)]["Manufacturer"].unique().tolist()
    add("core_brands_are_reckitt", "Dim_Product", "error",
        p[p["Brand"].isin(CORE_BRANDS) & (p["Manufacturer"] != CORE_MANUFACTURER)],
        f"All core brands belong to {CORE_MANUFACTURER} (found: {core_mfr})")
    return out


def summarize(results: list[CheckResult]) -> dict:
    sev = pd.Series([r.severity for r in results if not r.passed])
    return {
        "checks": len(results),
        "errors": int((sev == "error").sum()),
        "warnings": int((sev == "warning").sum()),
        "info": int(sum(r.severity == "info" for r in results)),
        "status": "fail" if (sev == "error").any() else "pass",
    }


def write_report(results: list[CheckResult], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    payload = {"summary": summary, "results": [asdict(r) for r in results]}
    (out_dir / "data_quality.json").write_text(json.dumps(payload, indent=2, default=str))

    icon = {True: "✅", False: {"error": "❌", "warning": "⚠️", "info": "ℹ️"}}
    lines = [
        "# Data quality report", "",
        f"**Status: {summary['status'].upper()}** · {summary['checks']} checks · "
        f"{summary['errors']} errors · {summary['warnings']} warnings · {summary['info']} info notes", "",
        "| | Check | Sheet | Rows | Detail |", "|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r.passed, ["error", "warning", "info"].index(r.severity))):
        mark = "ℹ️" if r.severity == "info" else (icon[True] if r.passed else icon[False][r.severity])
        lines.append(f"| {mark} | `{r.check}` | {r.sheet} | {r.failing_rows} | {r.detail} |")
    (out_dir / "data_quality.md").write_text("\n".join(lines) + "\n")
    return summary
