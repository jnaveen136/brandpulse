import pandas as pd
import pytest

from kpi.competitive import Competitive
from kpi.diagnostics import Diagnostics
from kpi.filters import Filters


@pytest.fixture(scope="module")
def comp(eng):
    return Competitive(eng)


@pytest.fixture(scope="module")
def diag(eng, comp):
    return Diagnostics(eng, comp)


def test_liquid_example_from_mentor(comp):
    # Dettol/Lizol Liquid -> Domex (Unilever), Ariel and Head & Shoulders (P&G); Lizol Liquid is the Reckitt tier
    m = comp.map[(comp.map["CoreProductName"] == "Dettol Variant 1")]
    assert set(m[m["Tier"] == "external"]["RivalBrand"]) == {"Domex", "Ariel", "Head & Shoulders"}
    assert set(m[m["Tier"] == "reckitt"]["RivalBrand"]) == {"Lizol"}
    assert "Gillette" not in set(m["RivalBrand"]) and "Lifebuoy" not in set(m["RivalBrand"])


def test_mapping_is_subcategory_only(comp, eng):
    p = eng.m.products.set_index("ProductID")
    m = comp.map
    assert (p.loc[m["CoreProductID"], "SubCategory"].values == p.loc[m["RivalProductID"], "SubCategory"].values).all()
    assert (m["CoreProductID"] != m["RivalProductID"]).all()
    # every possible same-SubCategory pair is present
    core = p[p["IsCore"]]
    expected = sum((p["SubCategory"] == sc).sum() - 1 for sc in core["SubCategory"])
    assert len(m) == expected


def test_tiers(comp):
    m = comp.map
    assert (m[m["Tier"] == "self"]["RivalBrand"] == m[m["Tier"] == "self"]["CoreBrand"]).all()
    assert (m[m["Tier"] == "external"]["RivalManufacturer"] != "Reckitt").all()
    assert (m[m["Tier"] == "reckitt"]["RivalManufacturer"] == "Reckitt").all()


def test_closest_rival_counts_variants_not_products(comp):
    for b in ["Dettol", "Harpic", "Veet", "Mortein", "Lizol"]:
        r = comp.closest_rivals(b)
        assert (r["variants_overlapped"] <= r["total_variants"]).all()
        assert set(r["RivalBrand"]).isdisjoint({"Dettol", "Harpic", "Veet", "Mortein", "Lizol"})


def test_price_gap_matches_manual(comp, eng):
    pp = comp.price_position("Dettol", "YTD")
    liquid = next(r for r in pp["by_subcategory"] if r["SubCategory"] == "Liquid")
    ours = eng.value("asp", Filters.make(brands="Dettol", subcategories="Liquid"), "YTD")
    theirs = eng.value("asp", Filters.make(brands=["Ariel", "Domex", "Head & Shoulders"], subcategories="Liquid"), "YTD")
    assert liquid["price_gap_pct"] == pytest.approx(100 * (ours / theirs - 1))


def test_market_share_gap_unavailable_for_lizol(comp):
    assert comp.market_share_gap("Lizol")["available"] is False


def test_variant_table_shape(comp):
    v = comp.variant_table("Dettol", "YTD")
    variants = [x for g in v["groups"] for x in g["variants"]]
    assert len(variants) == 5
    assert {g["SubCategory"] for g in v["groups"]} == {"Cleaner", "Liquid", "Soap"}
    for x in variants:
        assert all(r["Tier"] in ("self", "reckitt", "external") for r in x["rivals"])


@pytest.mark.parametrize("brand,period,mode", [("Dettol", "PQ", "yoy"), ("Harpic", "MTD", "previous"), ("Veet", "YTD", "yoy")])
def test_bridge_reconciles_exactly(diag, eng, brand, period, mode):
    x = diag.explain(brand, period, mode)
    total = sum(b["value"] for b in x["bridge"])
    assert total == pytest.approx(x["change"], abs=0.05)
    assert x["change"] == pytest.approx(x["revenue"] - x["revenue_prev"], abs=0.05)


def test_promotions_ended_is_detected(diag):
    # Festive runs Sep-Nov: December vs November must report the promotion ending
    x = diag.explain("Harpic", "MTD", "previous")
    promo = next(c for c in x["causes"] if c["id"] == "promotions")
    assert promo["title"] == "Promotions ended"
    assert promo["evidence"]["promo_revenue_share_pct"] == 0


def test_diagnostics_refuses_uncovered_comparison(diag):
    assert "error" in diag.explain("Dettol", ("2024-01-01", "2024-03-31"), "yoy")
