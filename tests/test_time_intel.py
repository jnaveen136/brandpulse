import pandas as pd
import pytest

from kpi import time_intel as T

AS_OF = pd.Timestamp("2025-12-30")  # a Tuesday, last day of data


@pytest.mark.parametrize("preset,start,end", [
    ("WTD", "2025-12-29", "2025-12-30"),
    ("MTD", "2025-12-01", "2025-12-30"),
    ("QTD", "2025-10-01", "2025-12-30"),
    ("YTD", "2025-01-01", "2025-12-30"),
    ("R7", "2025-12-24", "2025-12-30"),
    ("R30", "2025-12-01", "2025-12-30"),
    ("R90", "2025-10-02", "2025-12-30"),
    ("PM", "2025-11-01", "2025-11-30"),
    ("PQ", "2025-07-01", "2025-09-30"),
    ("L13W", "2025-10-01", "2025-12-30"),
    ("PY", "2024-01-01", "2024-12-31"),
])
def test_presets(preset, start, end):
    p = T.resolve(preset, AS_OF)
    assert (p.start, p.end) == (pd.Timestamp(start), pd.Timestamp(end))


@pytest.mark.parametrize("preset,days", [("R7", 7), ("R30", 30), ("R90", 90), ("L13W", 91)])
def test_window_lengths(preset, days):
    # L13W must be exactly 13 x 7 = 91 days (the old build produced 86)
    assert T.resolve(preset, AS_OF).days == days


def test_rolling_previous_is_adjacent_and_same_length():
    p = T.resolve("R30", AS_OF)
    c = T.comparison(p, "R30", "previous")
    assert c.days == 30 and c.end == p.start - pd.Timedelta(days=1)


def test_mtd_previous_is_same_days_last_month():
    p = T.resolve("MTD", pd.Timestamp("2025-03-31"))
    c = T.comparison(p, "MTD", "previous")
    assert (c.start, c.end) == (pd.Timestamp("2025-02-01"), pd.Timestamp("2025-02-28"))


def test_previous_quarter_comparison():
    p = T.resolve("PQ", AS_OF)
    c = T.comparison(p, "PQ", "previous")
    assert (c.start, c.end) == (pd.Timestamp("2025-04-01"), pd.Timestamp("2025-06-30"))


def test_yoy_shifts_one_year_and_handles_leap_day():
    p = T.Period("2024-02-29", "2024-03-05")
    c = T.comparison(p, None, "yoy")
    assert (c.start, c.end) == (pd.Timestamp("2023-02-28"), pd.Timestamp("2023-03-05"))


def test_coverage():
    p = T.Period("2023-12-01", "2024-01-30")
    assert p.coverage(pd.Timestamp("2024-01-01"), AS_OF) == pytest.approx(30 / 61)


def test_week_buckets_start_monday():
    d = pd.Series(pd.to_datetime(["2025-12-30", "2025-12-28"]))
    assert list(T.bucket(d, "W")) == [pd.Timestamp("2025-12-29"), pd.Timestamp("2025-12-22")]


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        T.resolve("XYZ", AS_OF)


# ---------------------------------------------------------------- calendar alignment at month / quarter ends
@pytest.mark.parametrize("preset,as_of,mode,start,end", [
    # a complete month is compared with the complete previous month (31 May was dropped before)
    ("MTD", "2025-06-30", "previous", "2025-05-01", "2025-05-31"),
    ("MTD", "2025-02-28", "previous", "2025-01-01", "2025-01-31"),
    # a partial month: the same day-of-month span
    ("MTD", "2025-06-15", "previous", "2025-05-01", "2025-05-15"),
    # 1-30 Mar -> 1-28 Feb (Feb has no 30th: clipped to the month end)
    ("MTD", "2025-03-30", "previous", "2025-02-01", "2025-02-28"),
    # a complete quarter vs the complete previous quarter (was 1 Oct-29 Dec)
    ("QTD", "2025-03-31", "previous", "2024-10-01", "2024-12-31"),
    # the dashboard default: QTD to 30 Dec vs 1 Jul-30 Sep (was 29 Sep: day-count, not calendar)
    ("QTD", "2025-12-30", "previous", "2025-07-01", "2025-09-30"),
    ("QTD", "2025-11-15", "previous", "2025-07-01", "2025-08-15"),
    # leap years: a complete Feb 2025 vs the complete Feb 2024 (29 days)
    ("YTD", "2025-02-28", "yoy", "2024-01-01", "2024-02-29"),
    ("MTD", "2025-02-28", "yoy", "2024-02-01", "2024-02-29"),
    ("YTD", "2025-12-30", "yoy", "2024-01-01", "2024-12-30"),   # 31 Dec 2025 is missing: compare to 30 Dec
])
def test_calendar_aligned_comparisons(preset, as_of, mode, start, end):
    c = T.comparison(T.resolve(preset, as_of), preset, mode)
    assert (c.start, c.end) == (pd.Timestamp(start), pd.Timestamp(end))


@pytest.mark.parametrize("preset", ["WTD", "MTD", "QTD", "YTD", "R7", "R30", "R90", "PM", "PQ", "L13W", "PY"])
@pytest.mark.parametrize("as_of", ["2025-01-01", "2025-02-28", "2025-03-31", "2025-06-30", "2025-12-30", "2024-02-29"])
def test_previous_period_never_overlaps(preset, as_of):
    p = T.resolve(preset, as_of)
    c = T.comparison(p, preset, "previous")
    assert c.end < p.start and c.start <= c.end
