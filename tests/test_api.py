import pytest
from fastapi.testclient import TestClient

from api.main import app
from kpi.filters import Filters

CORE = ["Dettol", "Harpic", "Veet", "Mortein", "Lizol"]
PAGES = ["overview", "variants", "competitors", "retailers", "marketing", "diagnostics"]


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_meta(client):
    m = client.get("/api/meta").json()
    assert [b["brand"] for b in m["core_brands"]] == CORE
    assert {p["id"] for p in m["presets"]} >= {"WTD", "MTD", "QTD", "YTD", "R7", "R30", "R90", "PM", "PQ", "L13W"}


@pytest.mark.parametrize("brand", CORE)
@pytest.mark.parametrize("page", PAGES)
def test_every_page_for_every_core_brand(client, brand, page):
    assert client.get(f"/api/brands/{brand}/{page}?period=YTD&mode=yoy").status_code == 200


def test_competitor_brand_is_not_selectable(client):
    assert client.get("/api/brands/Gillette/overview").status_code == 404


def test_bad_period_is_rejected(client):
    assert client.get("/api/brands/Dettol/overview?period=NOPE").status_code == 400


def test_overview_matches_engine_and_reacts_to_brand(client, eng):
    a = client.get("/api/brands/Dettol/overview?period=YTD").json()
    b = client.get("/api/brands/Veet/overview?period=YTD").json()
    rev = lambda p: next(k for k in p["kpis"] if k["kpi"] == "revenue")["current"]  # noqa: E731
    assert rev(a) == pytest.approx(eng.value("revenue", Filters.make(brands="Dettol"), "YTD"), rel=1e-6)
    assert rev(a) != rev(b)  # the old dashboard's static-chart bug


def test_global_filters_apply(client, eng):
    full = client.get("/api/brands/Harpic/overview?period=YTD").json()
    amz = client.get("/api/brands/Harpic/overview?period=YTD&retailers=Amazon").json()
    rev = lambda p: next(k for k in p["kpis"] if k["kpi"] == "revenue")["current"]  # noqa: E731
    assert rev(amz) == pytest.approx(eng.value("revenue", Filters.make(brands="Harpic", retailers="Amazon"), "YTD"), rel=1e-6)
    assert rev(amz) < rev(full)
    assert amz["filters"] == {"retailers": ["Amazon"]}


def test_custom_range(client):
    r = client.get("/api/brands/Lizol/overview?start=2025-03-01&end=2025-05-31&mode=previous").json()
    assert r["period"]["days"] == 92 and r["comparison"]["end"] == "2025-02-28"


def test_variants_page_has_matrix(client):
    v = client.get("/api/brands/Dettol/variants").json()
    assert len(v["matrix"]["rows"]) == 5
    liquid = next(r for r in v["matrix"]["rows"] if r["SubCategory"] == "Liquid")
    assert {b for b, on in liquid["cells"].items() if on} == {"Ariel", "Domex", "Head & Shoulders"}


def test_diagnostics_requires_comparison(client):
    assert client.get("/api/brands/Dettol/diagnostics?mode=none").status_code == 400


def test_generic_kpi_endpoint(client):
    rows = client.get("/api/kpi/revenue?brands=Dettol&by=Retailer&period=MTD").json()
    assert len(rows) == 10 and {"current", "previous", "delta_pct"} <= set(rows[0])
