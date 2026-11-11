"""Build the analytical model: validated, enriched tables in data/processed/.

Run with `python -m pipeline.build_model` (or `make data`).

Tables produced
  sales        one row per transaction, joined to product, retailer and
               warehouse, plus derived columns (GrossValue, DiscountValue,
               Cost, HasPromo, IsCore)
  reviews      one row per review, joined to product, with Sentiment and
               IsLeakage flags
  inventory    one row per stock snapshot, joined to product and warehouse,
               with BelowReorder flag
  market_share monthly share per brand (6 of 11 brands)
  marketing    campaign spend/ROI (company-level, no brand)
  events       competitor events (manufacturer-level)
  products, retailers, warehouses, calendar  dimension tables
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import ROOT, load_workbook
from .schema import CORE_BRANDS
from .validate import run_checks, write_report

PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
TABLES = ["sales", "reviews", "inventory", "market_share", "marketing", "events",
          "products", "retailers", "warehouses", "calendar"]


@dataclass
class Model:
    sales: pd.DataFrame
    reviews: pd.DataFrame
    inventory: pd.DataFrame
    market_share: pd.DataFrame
    marketing: pd.DataFrame
    events: pd.DataFrame
    products: pd.DataFrame
    retailers: pd.DataFrame
    warehouses: pd.DataFrame
    calendar: pd.DataFrame

    @property
    def min_date(self) -> pd.Timestamp:
        return self.sales["Date"].min()

    @property
    def max_date(self) -> pd.Timestamp:
        return self.sales["Date"].max()


def build(t: dict[str, pd.DataFrame]) -> Model:
    products = t["Dim_Product"].copy()
    products["IsCore"] = products["Brand"].isin(CORE_BRANDS)
    retailers = t["Dim_Retailer"].copy()
    warehouses = t["Dim_Warehouse"].rename(columns={"Region": "WarehouseRegion"})

    s = (t["Fact_Sales"]
         .merge(products, on="ProductID", how="left", validate="many_to_one")
         .merge(retailers, on="RetailerID", how="left", validate="many_to_one")
         .merge(warehouses, on="WarehouseID", how="left", validate="many_to_one"))
    s["Promotion"] = s["Promotion"].fillna("None")
    s["HasPromo"] = s["Promotion"] != "None"
    s["GrossValue"] = s["UnitsSold"] * s["MRP"]          # value at list price
    s["DiscountValue"] = s["GrossValue"] - s["Revenue"]  # money given away as discount
    s["Cost"] = s["UnitsSold"] * s["UnitCost"]
    s["Transactions"] = 1
    # Promotions run in fixed seasons (Summer: Mar-May, Festive: Sep-Nov) and
    # cover about half of the transactions in those months. Promo lift compares
    # promo vs non-promo rows *inside* those months, so seasonality isn't
    # mistaken for a promotion effect.
    ym = s["Date"].dt.to_period("M")
    s["InPromoSeason"] = ym.isin(set(ym[s["HasPromo"]]))
    s = s.sort_values(["Date", "SalesID"]).reset_index(drop=True)

    r = t["Fact_Reviews"].merge(products, on="ProductID", how="left", validate="many_to_one")
    r["Sentiment"] = np.select([r["Rating"] >= 4, r["Rating"] == 3], ["Positive", "Neutral"], "Negative")
    r["IsPositive"] = r["Rating"] >= 4
    r["IsLeakage"] = r["ReviewText"].str.contains("leak", case=False)

    inv = (t["Fact_Inventory"]
           .merge(products, on="ProductID", how="left", validate="many_to_one")
           .merge(warehouses, on="WarehouseID", how="left", validate="many_to_one"))
    inv["BelowReorder"] = inv["StockOnHand"] < inv["ReorderLevel"]

    ms = t["Fact_MarketShare"].copy()
    ms["IsCore"] = ms["Brand"].isin(CORE_BRANDS)

    return Model(
        sales=s, reviews=r, inventory=inv, market_share=ms,
        marketing=t["Fact_Marketing"].copy(), events=t["Fact_CompetitorEvents"].copy(),
        products=products, retailers=retailers, warehouses=warehouses, calendar=t["Dim_Date"].copy(),
    )


def save(model: Model, out_dir: Path = PROCESSED) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        getattr(model, name).to_parquet(out_dir / f"{name}.parquet", index=False)


def load_model(rebuild: bool = False) -> Model:
    """Load processed tables, building them from the workbook if needed."""
    if rebuild or not all((PROCESSED / f"{n}.parquet").exists() for n in TABLES):
        model = build(load_workbook())
        save(model)
        return model
    return Model(**{n: pd.read_parquet(PROCESSED / f"{n}.parquet") for n in TABLES})


def main() -> int:
    tables = load_workbook()
    results = run_checks(tables)
    summary = write_report(results, REPORTS)
    print(f"Validation: {summary}")
    for r in results:
        if not r.passed:
            print(f"  [{r.severity.upper():7}] {r.check} ({r.sheet}): {r.detail}")
    if summary["status"] == "fail":
        print("Validation failed: fix the errors above before building the model.")
        return 1
    model = build(tables)
    save(model)
    print(f"Wrote {len(TABLES)} tables to {PROCESSED.relative_to(ROOT)}/ "
          f"({len(model.sales):,} sales rows, {model.min_date.date()} to {model.max_date.date()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
