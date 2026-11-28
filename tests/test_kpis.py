"""Each KPI is checked against a value recomputed by hand from the raw workbook."""
import numpy as np
import pandas as pd
import pytest

from kpi import registry as R
from kpi.filters import Filters
from kpi.health_score import health_scores

YTD = ("2025-01-01", "2025-12-30")


def _ytd(df):
    return df[df["Date"].between(*YTD)]


@pytest.fixture(scope="module")
def dettol(raw):
    return _ytd(raw["sales"][raw["sales"]["Brand"] == "Dettol"])


F = Filters.make(brands="Dettol")


def test_revenue(eng, dettol):
    assert eng.value("revenue", F, "YTD") == pytest.approx(dettol["Revenue"].sum())


def test_units(eng, dettol):
    assert eng.value("units", F, "YTD") == pytest.approx(dettol["UnitsSold"].sum())


def test_asp_is_weighted_not_mean_of_prices(eng, dettol):
    expected = dettol["Revenue"].sum() / dettol["UnitsSold"].sum()
    assert eng.value("asp", F, "YTD") == pytest.approx(expected)
    assert abs(expected - dettol["SellingPrice"].mean()) > 0.01  # the naive mean would be wrong


def test_margin_pct(eng, dettol):
    assert eng.value("margin_pct", F, "YTD") == pytest.approx(100 * dettol["Margin"].sum() / dettol["Revenue"].sum())


def test_discount_pct(eng, dettol):
    gross = (dettol["UnitsSold"] * dettol["MRP"]).sum()
    assert eng.value("discount_pct", F, "YTD") == pytest.approx(100 * (gross - dettol["Revenue"].sum()) / gross)


def test_promo_revenue_share(eng, dettol):
    promo = dettol[dettol["Promotion"].notna()]["Revenue"].sum()
    assert eng.value("promo_revenue_share", F, "YTD") == pytest.approx(100 * promo / dettol["Revenue"].sum())


def test_promo_lift_uses_in_season_baseline(eng, dettol):
    season = dettol["Date"].dt.month.isin([3, 4, 5, 9, 10, 11])
    promo = dettol[dettol["Promotion"].notna()]
    base = dettol[season & dettol["Promotion"].isna()]
    expected = 100 * ((promo["UnitsSold"].mean() / base["UnitsSold"].mean()) - 1)
    assert eng.value("promo_lift_pct", F, "YTD") == pytest.approx(expected)


def test_tier1_share(eng, dettol):
    t1 = dettol[dettol["Tier"] == "Tier1"]["Revenue"].sum()
    assert eng.value("tier1_revenue_share", F, "YTD") == pytest.approx(100 * t1 / dettol["Revenue"].sum())


def test_revenue_growth_yoy(eng, raw):
    s = raw["sales"][raw["sales"]["Brand"] == "Dettol"]
    cur = s[s["Date"].between(*YTD)]["Revenue"].sum()
    prev = s[s["Date"].between("2024-01-01", "2024-12-30")]["Revenue"].sum()
    assert eng.value("revenue_growth_pct", F, "YTD", mode="yoy") == pytest.approx(100 * (cur / prev - 1))


def test_ratings(eng, raw):
    r = raw["Fact_Reviews"].merge(raw["Dim_Product"], on="ProductID")
    r = _ytd(r[r["Brand"] == "Dettol"])
    assert eng.value("avg_rating", F, "YTD") == pytest.approx(r["Rating"].mean())
    assert eng.value("positive_review_pct", F, "YTD") == pytest.approx(100 * (r["Rating"] >= 4).mean())
    leak = r["ReviewText"].str.contains("leak", case=False).mean()
    assert eng.value("leakage_complaint_pct", F, "YTD") == pytest.approx(100 * leak)


def test_stockout_risk(eng, raw):
    i = raw["Fact_Inventory"].merge(raw["Dim_Product"], on="ProductID")
    i = _ytd(i[i["Brand"] == "Dettol"])
    assert eng.value("stockout_risk_pct", F, "YTD") == pytest.approx(100 * (i["StockOnHand"] < i["ReorderLevel"]).mean())


def test_market_share_average(eng, raw):
    m = raw["Fact_MarketShare"]
    m = _ytd(m[m["Brand"] == "Dettol"])
    assert eng.value("market_share", F, "YTD") == pytest.approx(m["MarketSharePct"].mean())


def test_market_share_missing_brand_returns_none(eng):
    assert eng.value("market_share", Filters.make(brands="Lizol"), "YTD") is None


def test_campaign_roi_is_spend_weighted(eng, raw):
    m = _ytd(raw["Fact_Marketing"])
    assert eng.value("campaign_roi", None, "YTD") == pytest.approx((m["Spend"] * m["ROI"]).sum() / m["Spend"].sum())


def test_marketing_ignores_brand_filter_and_says_so(eng):
    res = eng.compare("campaign_spend", F, "YTD")
    assert "brands" in res["ignored_filters"]


def test_competitor_activity_index(eng, raw):
    ev = _ytd(raw["Fact_CompetitorEvents"])
    ev = ev[ev["Competitor"].isin(["Unilever", "P&G"])]
    pts = (ev["Event"].map(R.EVENT_WEIGHTS) * (1 + ev["PriceImpactPct"].abs() / 10)).sum()
    got = eng.value("competitor_activity_index", Filters.make(manufacturers=["Unilever", "P&G"]), "YTD")
    assert got == pytest.approx(pts * 30 / 364)


def test_price_index_is_100_overall(eng):
    # the whole selection compared with its own SKU averages must be exactly 100
    assert eng.value("price_index", F, "YTD") == pytest.approx(100)


def test_breakdown_sums_to_total(eng):
    for dim in ["Retailer", "Region", "Channel", "Category", "SubCategory"]:
        b = eng.breakdown("revenue", dim, F, "YTD")
        assert b["value"].sum() == pytest.approx(eng.value("revenue", F, "YTD")), dim


def test_timeseries_sums_to_total(eng):
    ts = eng.timeseries("revenue", "M", F, "YTD")
    assert len(ts) == 12 and ts["value"].sum() == pytest.approx(eng.value("revenue", F, "YTD"))
    assert ts["partial"].tolist() == [False] * 11 + [True]  # Dec ends on the 30th


def test_compare_flags_missing_history(eng):
    # yoy of 2024 YTD has no data at all -> previous is None, coverage 0
    res = eng.compare("revenue", F, ("2024-01-01", "2024-03-31"), mode="yoy")
    assert res["previous"] is None and res["comparison_coverage"] == 0


def test_filters_combine(eng, raw):
    s = raw["sales"]
    want = s[(s["Brand"] == "Dettol") & (s["Retailer"] == "Amazon") & (s["Region"] == "North")]["Revenue"].sum()
    f = Filters.make(brands="Dettol", retailers="Amazon", regions="North")
    assert eng.value("revenue", f, "ALL") == pytest.approx(want)


def test_every_registered_kpi_computes(eng):
    for k in R.KPIS:
        f = Filters.make(manufacturers=["Unilever", "P&G"]) if k.source == "events" else F
        v = eng.value(k.id, f, "YTD")
        assert v is None or np.isfinite(v), k.id


def test_health_score_covers_all_brands_and_labels_source(eng):
    h = health_scores(eng)
    assert len(h) == 11 and h["health_score"].between(0, 100).all()
    assert set(h[h["position_source"] == "proxy"].index) == {"Gillette", "Head & Shoulders", "Lizol", "Lux", "Mortein"}


# ---------------------------------------------------------------- aggregation edge cases (review fixes)
def test_market_share_of_several_brands_adds_up(eng, raw):
    # Dettol + Harpic = Reckitt's combined share: summed within a month, averaged over months
    m = _ytd(raw["Fact_MarketShare"])
    m = m[m["Brand"].isin(["Dettol", "Harpic"])]
    want = m.groupby("Date")["MarketSharePct"].sum().mean()
    got = eng.value("market_share", Filters.make(brands=["Dettol", "Harpic"]), "YTD")
    assert got == pytest.approx(want)
    assert got == pytest.approx(eng.value("market_share", Filters.make(brands="Dettol"), "YTD")
                                + eng.value("market_share", Filters.make(brands="Harpic"), "YTD"))


def test_market_share_breakdown_by_brand_is_unchanged(eng):
    b = eng.breakdown("market_share", "Brand", None, "YTD").set_index("Brand")["value"]
    assert b["Dettol"] == pytest.approx(eng.value("market_share", F, "YTD"))


def test_per_day_kpi_is_not_diluted_past_the_data_end(eng):
    f = Filters.make(manufacturers=["Unilever", "P&G"])
    inside = eng.value("competitor_activity_index", f, ("2025-12-01", "2025-12-30"))
    beyond = eng.value("competitor_activity_index", f, ("2025-12-01", "2026-01-30"))
    assert beyond == pytest.approx(inside)


def test_no_growth_against_a_partly_covered_comparison(eng):
    # Mar 2024 - Feb 2025 vs a year earlier: the comparison is only 2 of 12 months inside the data
    res = eng.compare("revenue", F, ("2024-03-01", "2025-02-28"), mode="yoy")
    assert 0 < res["comparison_coverage"] < 1
    assert res["previous"] is not None and res["delta"] is None and res["delta_pct"] is None


def test_growth_kpi_matches_hand_computed_previous_month(eng, raw):
    # Harpic MTD (1-30 Dec 2025) vs the same days of November
    s = raw["sales"][raw["sales"]["Brand"] == "Harpic"]
    cur = s[s["Date"].between("2025-12-01", "2025-12-30")]["Revenue"].sum()
    prev = s[s["Date"].between("2025-11-01", "2025-11-30")]["Revenue"].sum()
    got = eng.value("revenue_growth_pct", Filters.make(brands="Harpic"), "MTD", mode="previous")
    assert got == pytest.approx(100 * (cur / prev - 1))
