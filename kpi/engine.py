"""KPI engine: the single place where numbers are computed.

The notebook, the API, the dashboards and the LLM Q&A all call this class, so
a KPI shown in the React app, in Streamlit and in a chat answer is always the
same number.

    eng = Engine()
    eng.value("revenue", Filters.make(brands="Dettol"), period="YTD")
    eng.compare("asp", Filters.make(brands="Dettol"), period="MTD", mode="yoy")
    eng.breakdown("revenue", by="Retailer", filters=..., period="L13W")
    eng.timeseries("revenue", grain="M", filters=..., by="Brand")
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from pipeline.build_model import Model, load_model

from . import registry as R
from . import time_intel as T
from .filters import Filters

PeriodLike = str | T.Period | tuple | None


def _clean(x):
    """float('nan') -> None, numpy scalars -> python."""
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else x


class Engine:
    def __init__(self, model: Model | None = None):
        self.m = model or load_model()
        self.data_start = self.m.min_date
        self.data_end = self.m.max_date
        ms = self.m.market_share.copy()
        ms["MonthEnd"] = ms["Date"] + pd.offsets.MonthEnd(0)
        self._src = {
            "sales": self.m.sales, "reviews": self.m.reviews, "inventory": self.m.inventory,
            "market_share": ms, "marketing": self.m.marketing, "events": self.m.events,
        }

    # ------------------------------------------------------------------ periods
    def period(self, period: PeriodLike = "ALL", as_of=None) -> tuple[T.Period, str | None]:
        """Normalise a preset / Period / (start, end) into (Period, preset)."""
        as_of = pd.Timestamp(as_of) if as_of is not None else self.data_end
        if period is None:
            period = "ALL"
        if isinstance(period, T.Period):
            return period, None
        if isinstance(period, (tuple, list)):
            return T.Period(period[0], period[1], "Custom range"), None
        return T.resolve(period, as_of, data_start=self.data_start), period.upper()

    def comparison_period(self, period: PeriodLike, mode: str, as_of=None) -> T.Period | None:
        p, preset = self.period(period, as_of)
        return T.comparison(p, preset, mode)

    # ------------------------------------------------------------------ frames
    def frame(self, source: str, filters: Filters | None, period: T.Period | None) -> tuple[pd.DataFrame, list[str]]:
        df = self._src[source]
        if period is not None:
            if source == "market_share":  # monthly rows: keep months that overlap the period
                df = df[(df["Date"] <= period.end) & (df["MonthEnd"] >= period.start)]
            else:
                df = df[period.contains(df["Date"])]
        df, ignored = (filters or Filters()).apply(df, source)
        if source == "sales" and len(df):
            sku = df.groupby("ProductID")[["Revenue", "UnitsSold"]].transform("sum")
            df = df.assign(RefRevenue=df["UnitsSold"] * sku["Revenue"] / sku["UnitsSold"])
        return df, ignored

    def _aggregate(self, kpi: R.KPI, df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
        measures = R.MEASURES[kpi.source]
        if df.empty:
            cols = by + list(measures)
            return pd.DataFrame(columns=cols)
        missing = [c for c in by if c not in df.columns]
        if missing:
            raise ValueError(f"KPI {kpi.id!r} ({kpi.source}) can't be grouped by {missing}")
        mdf = pd.DataFrame({name: f(df) for name, f in measures.items()}, index=df.index)
        if by:
            mdf[by] = df[by]
            return mdf.groupby(by, observed=True, sort=False)[list(measures)].sum().reset_index()
        return mdf.sum().to_frame().T

    def _apply(self, kpi: R.KPI, agg: pd.DataFrame, days: int | pd.Series | None = None) -> np.ndarray:
        if agg.empty:
            return np.array([], dtype=float)
        v = np.asarray(kpi.formula(agg), dtype=float)
        if kpi.per_day and days is not None:
            v = v * 30.0 / np.asarray(days, dtype=float)
        return v

    # ------------------------------------------------------------------ public API
    def value(self, kpi_id: str, filters: Filters | None = None, period: PeriodLike = "ALL",
              as_of=None, mode: str = "yoy") -> float | None:
        """One number. Growth KPIs compare against `mode` (default: same period last year)."""
        kpi = R.get(kpi_id)
        if kpi.kind == "growth":
            return self.compare(kpi.base, filters, period, mode=mode, as_of=as_of)["delta_pct"]
        p, _ = self.period(period, as_of)
        df, _ = self.frame(kpi.source, filters, p)
        v = self._apply(kpi, self._aggregate(kpi, df, []), p.days)
        return _clean(v[0]) if len(v) else None

    def compare(self, kpi_id: str, filters: Filters | None = None, period: PeriodLike = "ALL",
                mode: str = "yoy", as_of=None) -> dict:
        """Current value vs. comparison period, with coverage flags."""
        kpi = R.get(kpi_id)
        if kpi.kind == "growth":
            inner = self.compare(kpi.base, filters, period, mode, as_of)
            return {**inner, "kpi": kpi.id, "name": kpi.name, "unit": kpi.unit,
                    "current": inner["delta_pct"], "previous": None, "delta": None, "delta_pct": None}
        p, preset = self.period(period, as_of)
        c = T.comparison(p, preset, mode)
        df, ignored = self.frame(kpi.source, filters, p)
        cur = self._apply(kpi, self._aggregate(kpi, df, []), p.days)
        cur = _clean(cur[0]) if len(cur) else None

        prev, cov = None, None
        if c is not None:
            cov = round(c.coverage(self.data_start, self.data_end), 4)
            if cov > 0:
                dfc, _ = self.frame(kpi.source, filters, c)
                pv = self._apply(kpi, self._aggregate(kpi, dfc, []), c.days)
                prev = _clean(pv[0]) if len(pv) else None
        delta = None if cur is None or prev is None else cur - prev
        delta_pct = None if delta is None or not prev else 100 * delta / abs(prev)
        return {
            "kpi": kpi.id, "name": kpi.name, "unit": kpi.unit, "group": kpi.group,
            "current": cur, "previous": prev, "delta": delta, "delta_pct": delta_pct,
            "higher_is_better": kpi.higher_is_better,
            "period": p.to_dict(), "comparison": c.to_dict() if c else None,
            "comparison_coverage": cov,
            "comparison_partial": cov is not None and cov < 1,
            "ignored_filters": ignored, "scope_note": kpi.scope_note,
        }

    def scorecard(self, kpi_ids: Iterable[str], filters: Filters | None = None,
                  period: PeriodLike = "ALL", mode: str = "yoy", as_of=None) -> list[dict]:
        return [self.compare(k, filters, period, mode, as_of) for k in kpi_ids]

    def breakdown(self, kpi_id: str, by: str | list[str], filters: Filters | None = None,
                  period: PeriodLike = "ALL", as_of=None, sort: bool = True) -> pd.DataFrame:
        """KPI value per group, e.g. revenue by Retailer."""
        kpi = R.get(kpi_id)
        by = [by] if isinstance(by, str) else list(by)
        if kpi.kind == "growth":
            out = self.breakdown_compare(kpi.base, by, filters, period, as_of=as_of)
            return out[by + ["delta_pct"]].rename(columns={"delta_pct": "value"})
        p, _ = self.period(period, as_of)
        df, _ = self.frame(kpi.source, filters, p)
        agg = self._aggregate(kpi, df, by)
        out = agg[by].copy()
        out["value"] = self._apply(kpi, agg, p.days)
        if sort:
            out = out.sort_values("value", ascending=False, na_position="last")
        return out.reset_index(drop=True)

    def breakdown_compare(self, kpi_id: str, by: str | list[str], filters: Filters | None = None,
                          period: PeriodLike = "ALL", mode: str = "yoy", as_of=None) -> pd.DataFrame:
        """Breakdown with current, previous, delta and delta_pct per group."""
        by = [by] if isinstance(by, str) else list(by)
        p, preset = self.period(period, as_of)
        c = T.comparison(p, preset, mode)
        cur = self.breakdown(kpi_id, by, filters, p, sort=False).rename(columns={"value": "current"})
        if c is None or c.coverage(self.data_start, self.data_end) == 0:
            cur["previous"] = np.nan
        else:
            prev = self.breakdown(kpi_id, by, filters, c, sort=False).rename(columns={"value": "previous"})
            cur = cur.merge(prev, on=by, how="outer")
        cur["delta"] = cur["current"] - cur["previous"]
        cur["delta_pct"] = 100 * cur["delta"] / cur["previous"].abs().replace(0, np.nan)
        return cur.sort_values("current", ascending=False, na_position="last").reset_index(drop=True)

    def timeseries(self, kpi_id: str, grain: str = "M", filters: Filters | None = None,
                   period: PeriodLike = "ALL", by: str | list[str] | None = None, as_of=None) -> pd.DataFrame:
        """KPI per day/week/month/quarter/year bucket (optionally split by a dimension).

        Buckets cut by the period edges or by the end of the data are flagged
        `partial`, so a chart can show them differently instead of as a dip."""
        kpi = R.get(kpi_id)
        if kpi.kind == "growth":
            raise ValueError("Use timeseries on the base KPI and compare buckets; growth KPIs need a period pair")
        by = [] if by is None else ([by] if isinstance(by, str) else list(by))
        p, _ = self.period(period, as_of)
        df, _ = self.frame(kpi.source, filters, p)
        if df.empty:
            return pd.DataFrame(columns=["bucket", *by, "value", "partial"])
        df = df.assign(bucket=T.bucket(df["Date"], grain))
        agg = self._aggregate(kpi, df, ["bucket"] + by)
        b_end = T.bucket_end(agg["bucket"], grain)
        lo = agg["bucket"].where(agg["bucket"] > p.start, p.start)
        hi = b_end.where(b_end < min(p.end, self.data_end), min(p.end, self.data_end))
        days = (hi - lo).dt.days + 1
        out = agg[["bucket"] + by].copy()
        out["value"] = self._apply(kpi, agg, days)
        full_days = (b_end - agg["bucket"]).dt.days + 1
        out["partial"] = (days < full_days).to_numpy() if kpi.source != "market_share" else False
        return out.sort_values(["bucket"] + by).reset_index(drop=True)

    # ------------------------------------------------------------------ helpers
    def catalog(self) -> pd.DataFrame:
        return R.catalog()

    def core_brands(self) -> list[str]:
        from pipeline.schema import CORE_BRANDS
        return list(CORE_BRANDS)
