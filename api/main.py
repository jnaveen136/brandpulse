"""BrandPulse REST API.

Run:  uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs

Every brand endpoint accepts the same query parameters:
  period     preset (WTD MTD QTD YTD R7 R30 R90 PM PQ L13W PY ALL) - default YTD
  start,end  custom range (YYYY-MM-DD), overrides period
  mode       comparison: yoy | previous | none - default yoy
  as_of      anchor date for presets - default last data date
  retailers, channels, tiers, regions   comma-separated global filters
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kpi import time_intel as T
from kpi.filters import Filters

from .service import ROOT, BrandNotFound, Ctx, Service, jsonable

app = FastAPI(title="BrandPulse API", version="1.0",
              description="Brand intelligence for Reckitt's core brands vs. their real competitors.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_service: Service | None = None


def svc() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service


def _split(s: str | None) -> tuple:
    return tuple(x.strip() for x in s.split(",") if x.strip()) if s else ()


def ctx(period: str = Query("YTD"), mode: str = Query("yoy"), as_of: str | None = None,
        start: str | None = None, end: str | None = None,
        retailers: str | None = None, channels: str | None = None,
        tiers: str | None = None, regions: str | None = None) -> Ctx:
    if mode not in T.COMPARE_MODES:
        raise HTTPException(400, f"mode must be one of {list(T.COMPARE_MODES)}")
    if start and end:
        per = (start, end)
    elif period.upper() in T.PRESETS:
        per = period.upper()
    else:
        raise HTTPException(400, f"period must be one of {list(T.PRESETS)} or give start and end")
    f = Filters(retailers=_split(retailers), channels=_split(channels), tiers=_split(tiers), regions=_split(regions))
    return Ctx(period=per, mode=mode, as_of=as_of, filters=f)


@app.exception_handler(BrandNotFound)
async def _brand_404(_, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _bad_request(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/meta")
def meta():
    return svc().meta()


@app.get("/api/health-scores")
def health_scores(c: Ctx = Depends(ctx)):
    return svc().health(c.period, c.mode if c.mode != "none" else "yoy", c.as_of)


@app.get("/api/brands/{brand}/overview")
def overview(brand: str, c: Ctx = Depends(ctx)):
    return svc().overview(brand, c)


@app.get("/api/brands/{brand}/variants")
def variants(brand: str, c: Ctx = Depends(ctx)):
    return svc().variants(brand, c)


@app.get("/api/brands/{brand}/competitors")
def competitors(brand: str, c: Ctx = Depends(ctx)):
    return svc().competitors(brand, c)


@app.get("/api/brands/{brand}/retailers")
def retailers(brand: str, c: Ctx = Depends(ctx)):
    return svc().retailers(brand, c)


@app.get("/api/brands/{brand}/marketing")
def marketing(brand: str, c: Ctx = Depends(ctx)):
    return svc().marketing(brand, c)


@app.get("/api/brands/{brand}/diagnostics")
def diagnostics(brand: str, c: Ctx = Depends(ctx), subcategory: str | None = None, product: str | None = None):
    if c.mode == "none":
        raise HTTPException(400, "Diagnostics need a comparison: use mode=yoy or mode=previous")
    return svc().diagnostics(brand, c, subcategory, product)


@app.get("/api/kpi/{kpi_id}")
def kpi(kpi_id: str, c: Ctx = Depends(ctx), brands: str | None = None, subcategories: str | None = None,
        by: str | None = None, grain: str | None = None):
    """Generic access to any registered KPI: a value with comparison, a breakdown, or a time series."""
    f = c.filters.with_(brands=_split(brands), subcategories=_split(subcategories))
    e = svc().e
    if grain:
        return jsonable(e.timeseries(kpi_id, grain, f, c.period, by=by, as_of=c.as_of))
    if by:
        return jsonable(e.breakdown_compare(kpi_id, by, f, c.period, c.mode, c.as_of))
    return jsonable(e.compare(kpi_id, f, c.period, c.mode, c.as_of))


@app.get("/api/data-quality")
def data_quality():
    p = ROOT / "reports" / "data_quality.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"detail": "Run `make data` first"}


# The LLM Q&A endpoint is registered by llm/ when that package is present (Phase 6)
try:  # pragma: no cover
    from llm.routes import router as llm_router
    app.include_router(llm_router)
except ImportError:
    pass

# Serve the built React app (web/dist) from the same server, if it has been built
DIST = ROOT / "web" / "dist"
if DIST.exists() and not os.environ.get("BRANDPULSE_API_ONLY"):
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
