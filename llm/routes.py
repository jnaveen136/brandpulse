"""FastAPI routes for the Q&A layer: /api/ask, /api/ask/explain, /api/ask/status."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kpi import time_intel as T
from pipeline.schema import CORE_BRANDS

router = APIRouter(prefix="/api/ask", tags=["ask"])
_assistant = None
_lock = threading.Lock()


def assistant():
    """One assistant per server. The page fires /status and /ask together; the lock stops both
    requests from building their own copy (and downloading the embedding model twice)."""
    global _assistant
    if _assistant is None:
        with _lock:
            if _assistant is None:
                from api.main import svc  # share the API's engine and caches
                from .assistant import Assistant
                _assistant = Assistant(svc())
    return _assistant


class Question(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    brand: str = "Dettol"
    period: str = "YTD"
    mode: str = "yoy"
    history: list[dict] = []


def _check(brand: str, period: str, mode: str):
    if brand not in CORE_BRANDS:
        raise HTTPException(400, f"brand must be one of {CORE_BRANDS}")
    if period.upper() not in T.PRESETS:
        raise HTTPException(400, f"period must be one of {list(T.PRESETS)}")
    if mode not in ("yoy", "previous"):
        raise HTTPException(400, "mode must be yoy or previous")


@router.get("/status")
def status():
    return assistant().status()


@router.post("")
def ask(q: Question):
    _check(q.brand, q.period, q.mode)
    return assistant().ask(q.question, q.brand, q.period.upper(), q.mode, q.history)


@router.post("/explain")
def explain(brand: str, period: str = "MTD", mode: str = "yoy", subcategory: str | None = None):
    _check(brand, period, mode)
    return assistant().explain(brand, period.upper(), mode, subcategory or None)
