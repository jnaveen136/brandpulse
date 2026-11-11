# Data quality report

**Status: PASS** · 46 checks · 0 errors · 4 warnings · 4 info notes

| | Check | Sheet | Rows | Detail |
|---|---|---|---|---|
| ⚠️ | `calendar_complete` | Dim_Date | 1 | Calendar should cover every day of each year. Missing: 2025-12-31. Year-end comparisons treat the last year as ending one day early. |
| ⚠️ | `market_share_coverage` | Fact_MarketShare | 5 | Market share exists for 6 of 11 brands. Missing: Gillette, Head & Shoulders, Lizol, Lux, Mortein. Core brands without share: Lizol, Mortein. |
| ⚠️ | `marketing_has_no_brand` | Fact_Marketing | 48 | Fact_Marketing has no Brand column: campaign spend and ROI can only be reported for the company as a whole. |
| ⚠️ | `competitor_events_are_manufacturer_level` | Fact_CompetitorEvents | 51 | Events are recorded per manufacturer (P&G, SC Johnson, Unilever), not per brand. SC Johnson has events but no products in the data. |
| ℹ️ | `category_not_brand_consistent` | Dim_Product | 11 | 11 of 11 brands have SKUs in more than one Category, so competitors are matched on SubCategory only (see docs/DECISIONS.md). |
| ℹ️ | `review_text_templated` | Fact_Reviews | 3 | ReviewText has only 3 fixed phrases tied to rating: 2★: Average quality, Packaging leakage issue; 3★: Average quality, Packaging leakage issue; 4★: Excellent quality; 5★: Excellent quality. Only the leakage complaint adds information beyond the rating. |
| ✅ | `primary_key_unique` | Dim_Product | 0 | ProductID must be unique |
| ✅ | `no_unexpected_nulls` | Dim_Product | 0 | No nulls outside none |
| ✅ | `primary_key_unique` | Dim_Retailer | 0 | RetailerID must be unique |
| ✅ | `no_unexpected_nulls` | Dim_Retailer | 0 | No nulls outside none |
| ✅ | `primary_key_unique` | Dim_Warehouse | 0 | WarehouseID must be unique |
| ✅ | `no_unexpected_nulls` | Dim_Warehouse | 0 | No nulls outside none |
| ✅ | `primary_key_unique` | Dim_Date | 0 | Date must be unique |
| ✅ | `no_unexpected_nulls` | Dim_Date | 0 | No nulls outside none |
| ✅ | `primary_key_unique` | Fact_Sales | 0 | SalesID must be unique |
| ✅ | `no_unexpected_nulls` | Fact_Sales | 0 | No nulls outside ['Promotion'] |
| ✅ | `primary_key_unique` | Fact_Reviews | 0 | ReviewID must be unique |
| ✅ | `no_unexpected_nulls` | Fact_Reviews | 0 | No nulls outside none |
| ✅ | `no_unexpected_nulls` | Fact_Inventory | 0 | No nulls outside none |
| ✅ | `primary_key_unique` | Fact_MarketShare | 0 | Date+Brand must be unique |
| ✅ | `no_unexpected_nulls` | Fact_MarketShare | 0 | No nulls outside none |
| ✅ | `no_unexpected_nulls` | Fact_Marketing | 0 | No nulls outside none |
| ✅ | `no_unexpected_nulls` | Fact_CompetitorEvents | 0 | No nulls outside none |
| ✅ | `foreign_key` | Fact_Sales | 0 | Fact_Sales.ProductID must exist in Dim_Product.ProductID |
| ✅ | `foreign_key` | Fact_Sales | 0 | Fact_Sales.RetailerID must exist in Dim_Retailer.RetailerID |
| ✅ | `foreign_key` | Fact_Sales | 0 | Fact_Sales.WarehouseID must exist in Dim_Warehouse.WarehouseID |
| ✅ | `foreign_key` | Fact_Sales | 0 | Fact_Sales.Date must exist in Dim_Date.Date |
| ✅ | `foreign_key` | Fact_Reviews | 0 | Fact_Reviews.ProductID must exist in Dim_Product.ProductID |
| ✅ | `foreign_key` | Fact_Inventory | 0 | Fact_Inventory.ProductID must exist in Dim_Product.ProductID |
| ✅ | `foreign_key` | Fact_Inventory | 0 | Fact_Inventory.WarehouseID must exist in Dim_Warehouse.WarehouseID |
| ✅ | `foreign_key` | Fact_MarketShare | 0 | Fact_MarketShare.Brand must exist in Dim_Product.Brand |
| ✅ | `revenue_equals_units_x_price` | Fact_Sales | 0 | Revenue = UnitsSold x SellingPrice |
| ✅ | `margin_equals_price_minus_cost` | Fact_Sales | 0 | Margin = (SellingPrice - UnitCost) x UnitsSold |
| ✅ | `units_positive` | Fact_Sales | 0 | UnitsSold > 0 |
| ✅ | `revenue_positive` | Fact_Sales | 0 | Revenue > 0 |
| ✅ | `price_not_above_mrp` | Fact_Sales | 0 | SellingPrice <= MRP |
| ✅ | `cost_below_mrp` | Dim_Product | 0 | UnitCost < MRP |
| ✅ | `rating_in_1_to_5` | Fact_Reviews | 0 | Rating between 1 and 5 |
| ✅ | `stock_non_negative` | Fact_Inventory | 0 | StockOnHand >= 0 |
| ✅ | `share_in_0_100` | Fact_MarketShare | 0 | MarketSharePct between 0 and 100 |
| ✅ | `core_brands_are_reckitt` | Dim_Product | 0 | All core brands belong to Reckitt (found: ['Reckitt']) |
| ✅ | `margin_positive` | Fact_Sales | 0 | Margin > 0 (loss-making rows) |
| ✅ | `non_promo_sold_at_mrp` | Fact_Sales | 0 | Rows without a promotion should sell at MRP |
| ✅ | `promo_rows_discounted` | Fact_Sales | 0 | Promotion rows should carry a discount |
| ℹ️ | `sales_every_day` | Fact_Sales | 0 | Sales exist on 730 of 730 calendar days |
| ℹ️ | `market_share_is_within_tracked_set` | Fact_MarketShare | 0 | The 6 brands' shares add up to 99.0-101.8% each month, so the share is measured within this set of brands, not the whole market. |
