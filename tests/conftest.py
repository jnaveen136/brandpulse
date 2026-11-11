import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kpi.engine import Engine  # noqa: E402
from pipeline.ingest import load_workbook, workbook_path  # noqa: E402


@pytest.fixture(scope="session")
def raw():
    """The workbook read straight from Excel with plain pandas, independent of the pipeline.
    Tests recompute expected values from this so they don't just re-run engine code."""
    s = pd.read_excel(workbook_path(), sheet_name=None)
    for df in s.values():
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
    s["sales"] = (s["Fact_Sales"].merge(s["Dim_Product"], on="ProductID")
                  .merge(s["Dim_Retailer"], on="RetailerID"))
    return s


@pytest.fixture(scope="session")
def tables():
    return load_workbook()


@pytest.fixture(scope="session")
def eng():
    return Engine()
