"""Load the workbook and enforce the schema contract in pipeline/schema.py."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .schema import SHEETS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = ROOT / "data" / "raw" / "Brand_Intelligence_Accelerator_Dataset_v1.xlsx"


class SchemaError(ValueError):
    pass


def workbook_path() -> Path:
    env = os.environ.get("BRANDPULSE_DATA")
    return (ROOT / env) if env and not os.path.isabs(env) else Path(env or DEFAULT_WORKBOOK)


def _coerce(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    spec = SHEETS[sheet]
    missing = [c for c in spec["columns"] if c not in df.columns]
    if missing:
        raise SchemaError(f"{sheet}: missing columns {missing}")
    df = df[list(spec["columns"])].copy()
    for col, kind in spec["columns"].items():
        if kind == "date":
            df[col] = pd.to_datetime(df[col], errors="raise").dt.normalize()
        elif kind == "int":
            df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")
        elif kind == "float":
            df[col] = pd.to_numeric(df[col], errors="raise").astype("float64")
        else:
            # keep NaN as NaN (e.g. Promotion), strip stray whitespace otherwise
            df[col] = df[col].where(df[col].isna(), df[col].astype(str).str.strip())
    return df


def load_workbook(path: str | Path | None = None) -> dict[str, pd.DataFrame]:
    """Read every sheet in the contract, typed. Extra sheets are ignored."""
    path = Path(path) if path else workbook_path()
    xls = pd.ExcelFile(path)
    absent = [s for s in SHEETS if s not in xls.sheet_names]
    if absent:
        raise SchemaError(f"Workbook {path.name} is missing sheets: {absent}")
    return {name: _coerce(pd.read_excel(xls, sheet_name=name), name) for name in SHEETS}
