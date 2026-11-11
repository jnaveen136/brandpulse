"""Schema contract for the Brand Intelligence Accelerator workbook.

Every sheet the pipeline reads is declared here with its columns, types and
primary key. Ingestion fails loudly if a sheet or column is missing, so a
changed workbook can't silently produce wrong KPIs.
"""
from __future__ import annotations

CORE_MANUFACTURER = "Reckitt"
CORE_BRANDS = ["Dettol", "Harpic", "Veet", "Mortein", "Lizol"]

# column -> dtype ("str", "int", "float", "date")
SHEETS: dict[str, dict] = {
    "Dim_Product": {
        "columns": {
            "ProductID": "str", "ProductName": "str", "Brand": "str", "Manufacturer": "str",
            "Category": "str", "SubCategory": "str", "MRP": "float", "UnitCost": "float",
        },
        "primary_key": ["ProductID"],
    },
    "Dim_Retailer": {
        "columns": {"RetailerID": "str", "Retailer": "str", "Channel": "str", "Tier": "str"},
        "primary_key": ["RetailerID"],
    },
    "Dim_Warehouse": {
        "columns": {"WarehouseID": "str", "Warehouse": "str", "Region": "str"},
        "primary_key": ["WarehouseID"],
    },
    "Dim_Date": {
        "columns": {"Date": "date", "Year": "int", "Month": "int", "MonthName": "str", "Week": "int"},
        "primary_key": ["Date"],
    },
    "Fact_Sales": {
        "columns": {
            "SalesID": "str", "Date": "date", "ProductID": "str", "RetailerID": "str",
            "Region": "str", "WarehouseID": "str", "UnitsSold": "int", "SellingPrice": "float",
            "Revenue": "float", "Margin": "float", "Promotion": "str",
        },
        "primary_key": ["SalesID"],
        "nullable": ["Promotion"],  # blank = no promotion running
    },
    "Fact_Reviews": {
        "columns": {"ReviewID": "str", "Date": "date", "ProductID": "str", "Rating": "int", "ReviewText": "str"},
        "primary_key": ["ReviewID"],
    },
    "Fact_Inventory": {
        "columns": {
            "Date": "date", "ProductID": "str", "WarehouseID": "str",
            "StockOnHand": "int", "ReorderLevel": "int", "LeadTimeDays": "int",
        },
        # No unique key: snapshots are row-aligned with Fact_Sales, so the
        # same product/warehouse/day can appear more than once.
        "primary_key": None,
    },
    "Fact_MarketShare": {
        "columns": {"Date": "date", "Brand": "str", "MarketSharePct": "float"},
        "primary_key": ["Date", "Brand"],
    },
    "Fact_Marketing": {
        "columns": {
            "Date": "date", "Campaign": "str", "Channel": "str", "Spend": "float",
            "Impressions": "int", "Conversions": "int", "ROI": "float",
        },
        "primary_key": None,
    },
    "Fact_CompetitorEvents": {
        "columns": {"Date": "date", "Competitor": "str", "Event": "str", "PriceImpactPct": "float"},
        "primary_key": None,
    },
}

# Foreign keys: (child sheet, column) -> (parent sheet, column)
FOREIGN_KEYS = [
    ("Fact_Sales", "ProductID", "Dim_Product", "ProductID"),
    ("Fact_Sales", "RetailerID", "Dim_Retailer", "RetailerID"),
    ("Fact_Sales", "WarehouseID", "Dim_Warehouse", "WarehouseID"),
    ("Fact_Sales", "Date", "Dim_Date", "Date"),
    ("Fact_Reviews", "ProductID", "Dim_Product", "ProductID"),
    ("Fact_Inventory", "ProductID", "Dim_Product", "ProductID"),
    ("Fact_Inventory", "WarehouseID", "Dim_Warehouse", "WarehouseID"),
    ("Fact_MarketShare", "Brand", "Dim_Product", "Brand"),
]
