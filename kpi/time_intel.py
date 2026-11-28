"""Time Intelligence: turn a preset (MTD, YTD, Rolling 30 ...) into a date range,
and work out the period it should be compared against.

All ranges are inclusive [start, end] and anchored on an `as_of` date, which
defaults to the last day with data (2025-12-30). Weeks start on Monday.

Comparison modes
  previous - the period immediately before, of the same shape
             (MTD -> same days of last month, Rolling 30 -> the 30 days before)
  yoy      - the same dates one year earlier ("Same Period Last Year")
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

PRESETS = {
    "WTD": "Week to date",
    "MTD": "Month to date",
    "QTD": "Quarter to date",
    "YTD": "Year to date",
    "R7": "Rolling 7 days",
    "R30": "Rolling 30 days",
    "R90": "Rolling 90 days",
    "PM": "Previous month",
    "PQ": "Previous quarter",
    "L13W": "Last 13 weeks",
    "PY": "Previous year",
    "ALL": "All data",
}
COMPARE_MODES = {"previous": "Previous period", "yoy": "Same period last year", "none": "No comparison"}


@dataclass(frozen=True)
class Period:
    start: pd.Timestamp
    end: pd.Timestamp
    label: str = ""

    def __post_init__(self):
        object.__setattr__(self, "start", pd.Timestamp(self.start).normalize())
        object.__setattr__(self, "end", pd.Timestamp(self.end).normalize())
        if self.end < self.start:
            raise ValueError(f"Period end {self.end.date()} is before start {self.start.date()}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, dates: pd.Series) -> pd.Series:
        return dates.between(self.start, self.end)

    def coverage(self, data_start: pd.Timestamp, data_end: pd.Timestamp) -> float:
        """Share of this period's days that fall inside the data's date range."""
        lo, hi = max(self.start, data_start), min(self.end, data_end)
        return 0.0 if hi < lo else ((hi - lo).days + 1) / self.days

    def to_dict(self) -> dict:
        return {"start": self.start.strftime("%Y-%m-%d"), "end": self.end.strftime("%Y-%m-%d"),
                "days": self.days, "label": self.label}


def _quarter_start(d: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _is_month_end(d: pd.Timestamp) -> bool:
    return (d + pd.Timedelta(days=1)).day == 1


def _shift_months(d: pd.Timestamp, months: int) -> pd.Timestamp:
    """Move a date by whole months, calendar-aligned (the DAX DATEADD convention).

    A month-end date stays a month-end date: 30 Jun -> 31 May, 31 Mar -> 31 Dec,
    28 Feb 2025 -> 29 Feb 2024. Without this rule a complete month or quarter is
    compared with a truncated one (30 Jun MTD vs 1-30 May would drop 31 May)."""
    out = d + pd.DateOffset(months=months)  # 31 Mar - 1 month -> 28/29 Feb (clipped)
    return out + pd.offsets.MonthEnd(0) if _is_month_end(d) else out


def _shift_years(d: pd.Timestamp, years: int) -> pd.Timestamp:
    return _shift_months(d, 12 * years)  # 29 Feb 2024 -> 28 Feb 2023; 28 Feb 2025 -> 29 Feb 2024


def _shift_back(period: "Period", months: int, label: str) -> "Period":
    """The same calendar span `months` earlier, ending before the original period starts."""
    start = _shift_months(period.start, -months)
    end = min(_shift_months(period.end, -months), period.start - pd.Timedelta(days=1))
    return Period(start, end, label)


def resolve(preset: str, as_of, data_start=None) -> Period:
    """Date range for a preset, ending on (or just before) `as_of`."""
    p = preset.upper()
    d = pd.Timestamp(as_of).normalize()
    if p == "WTD":
        return Period(d - pd.Timedelta(days=d.weekday()), d, PRESETS[p])
    if p == "MTD":
        return Period(d.replace(day=1), d, PRESETS[p])
    if p == "QTD":
        return Period(_quarter_start(d), d, PRESETS[p])
    if p == "YTD":
        return Period(d.replace(month=1, day=1), d, PRESETS[p])
    if p in ("R7", "R30", "R90"):
        n = int(p[1:])
        return Period(d - pd.Timedelta(days=n - 1), d, PRESETS[p])
    if p == "L13W":
        return Period(d - pd.Timedelta(days=13 * 7 - 1), d, PRESETS[p])
    if p == "PM":
        end = d.replace(day=1) - pd.Timedelta(days=1)
        return Period(end.replace(day=1), end, PRESETS[p])
    if p == "PQ":
        end = _quarter_start(d) - pd.Timedelta(days=1)
        return Period(_quarter_start(end), end, PRESETS[p])
    if p == "PY":
        y = d.year - 1
        return Period(pd.Timestamp(y, 1, 1), pd.Timestamp(y, 12, 31), PRESETS[p])
    if p == "ALL":
        if data_start is None:
            raise ValueError("ALL needs data_start")
        return Period(data_start, d, PRESETS[p])
    raise ValueError(f"Unknown preset {preset!r}. Use one of {list(PRESETS)}")


def comparison(period: Period, preset: str | None, mode: str) -> Period | None:
    """The period to compare `period` against."""
    if mode in (None, "none"):
        return None
    if mode == "yoy":
        return Period(_shift_years(period.start, -1), _shift_years(period.end, -1), "Same period last year")
    if mode != "previous":
        raise ValueError(f"Unknown comparison mode {mode!r}")

    p = (preset or "").upper()
    s, e = period.start, period.end
    # MTD / QTD: the same days of the previous month / quarter, calendar-aligned. If the current
    # period ends on a month end (a complete month), so does the comparison: 1-30 Jun vs 1-31 May.
    if p == "MTD":
        return _shift_back(period, 1, "Same days last month")
    if p == "QTD":
        return _shift_back(period, 3, "Same days last quarter")
    if p == "YTD":
        return Period(_shift_years(s, -1), _shift_years(e, -1), "Same days last year")
    if p == "PM":
        end = s - pd.Timedelta(days=1)
        return Period(end.replace(day=1), end, "Month before")
    if p == "PQ":
        end = s - pd.Timedelta(days=1)
        return Period(_quarter_start(end), end, "Quarter before")
    if p == "PY":
        return Period(_shift_years(s, -1), _shift_years(e, -1), "Year before")
    # WTD, rolling windows, L13W, ALL and custom ranges: the same number of days immediately before
    return Period(s - pd.Timedelta(days=period.days), s - pd.Timedelta(days=1), "Previous period")


def bucket(dates: pd.Series, grain: str) -> pd.Series:
    """Start date of the day/week/month/quarter/year bucket each date falls in."""
    g = grain.upper()
    if g == "D":
        return dates.dt.normalize()
    if g == "W":
        return (dates - pd.to_timedelta(dates.dt.day_of_week, unit="D")).dt.normalize()
    if g in ("M", "Q", "Y"):
        return dates.dt.to_period({"M": "M", "Q": "Q", "Y": "Y"}[g]).dt.start_time
    raise ValueError(f"Unknown grain {grain!r}; use D, W, M, Q or Y")


def bucket_end(starts: pd.Series, grain: str) -> pd.Series:
    g = grain.upper()
    if g == "D":
        return starts
    if g == "W":
        return starts + pd.Timedelta(days=6)
    off = {"M": pd.offsets.MonthEnd(1), "Q": pd.offsets.QuarterEnd(1), "Y": pd.offsets.YearEnd(1)}[g]
    return starts + off
