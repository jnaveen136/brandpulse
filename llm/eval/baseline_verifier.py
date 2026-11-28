"""BASELINE (v1) verifier, kept unchanged for the before/after evaluation in llm/eval/verifier_eval.py.

Do not use in the app: it accepts differences and % changes between ANY two tool numbers,
so with thousands of numbers in a result almost any invented percentage passes.

Grounding check: every figure in an answer must come from a tool result.

A figure is "supported" when some number in the tool results (or a simple
difference / % change between two of them, the arithmetic an analyst would
do) rounds to it at the precision it is written with. "₹40.7 L" means
₹40,70,000 ± ₹5,000; "-2.6%" means 2.55 to 2.65 (sign-insensitive, because
"down 2.6%" is how people write a negative change).

Ignored: dates, years, product/period labels (Variant 3, Q2, Tier1, R30) and
small whole numbers without a unit (counts like "5 variants").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

SCALE = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
         "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
STRIP = [
    r"\b\d{4}-\d{2}-\d{2}\b",                                  # ISO dates
    rf"\b\d{{1,2}}\s+{MONTHS}\.?(?:\s+\d{{4}})?\b",            # 9 Feb 2025
    rf"\b{MONTHS}\.?\s+\d{{1,2}}(?:,\s*\d{{4}})?\b",           # Feb 9, 2025
    rf"\b{MONTHS}\.?\s+'?\d{{2,4}}\b",                         # Feb 2025 / Feb '25
    r"\b(?:19|20)\d{2}\b",                                     # years
    r"\bvariant\s*\d+\b", r"\bsku\s*\d+\b", r"\bq[1-4]\b", r"\btier\s*-?\s*[12]\b",
    r"\b(?:r7|r30|r90|l13w|wtd|mtd|qtd|ytd)\b", r"\blast\s+\d+\s+(?:days|weeks|months)\b",
    r"\b(?:rolling|past)\s+\d+\s+days\b", r"\b\d+\s*(?:st|nd|rd|th)\b",
]
NUM = re.compile(
    r"(?P<cur>₹|rs\.?\s*|inr\s*)?(?P<sign>[-−+])?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<suf>crores?|cr|lakhs?|lac|l|k|thousand|mn|million|m|%|pp|percentage points?|×|x|★|stars?)?(?![a-z])",
    re.I)


@dataclass
class Figure:
    text: str
    value: float
    tol: float
    unit: str


def extract(text: str) -> list[Figure]:
    t = text
    for pat in STRIP:
        t = re.sub(pat, " ", t, flags=re.I)
    out = []
    for m in NUM.finditer(t):
        raw = m.group("num")
        suf = (m.group("suf") or "").lower()
        cur = bool(m.group("cur"))
        v = float(raw.replace(",", ""))
        dec = len(raw.split(".")[1]) if "." in raw else 0
        scale = SCALE.get(suf, 1.0)
        if not cur and not suf and dec == 0 and v <= 12:
            continue  # small counts ("5 variants", "3 rivals")
        if not cur and suf in ("m",) and v <= 12:
            continue
        tol = 0.5 * 10 ** (-dec) * scale
        if dec == 0 and "," in raw:
            tol = 0.5 * scale  # exact rupee amount
        out.append(Figure(m.group(0).strip(), v * scale, max(tol, 1e-9), suf or ("₹" if cur else "")))
    return out


def _numbers(o, acc: list[float]) -> None:
    if isinstance(o, bool) or o is None:
        return
    if isinstance(o, (int, float)):
        acc.append(abs(float(o)))
    elif isinstance(o, str):  # figures quoted inside tool text (cause descriptions, definitions)
        acc.extend(abs(f.value) for f in extract(o))
    elif isinstance(o, dict):
        for v in o.values():
            _numbers(v, acc)
    elif isinstance(o, (list, tuple)):
        acc.append(float(len(o)))
        for v in o:
            _numbers(v, acc)


def candidates(results: list[dict], extra_text: str = "") -> np.ndarray:
    base: list[float] = []
    for r in results:
        acc: list[float] = []
        _numbers(r, acc)
        base.extend(acc)
    base.extend(f.value for f in extract(extra_text))
    a = np.unique(np.array(base, dtype=float)) if base else np.array([])
    if 1 < len(a) <= 600:  # simple arithmetic between two figures: differences and % changes
        diff = np.abs(a[:, None] - a[None, :]).ravel()
        with np.errstate(divide="ignore", invalid="ignore"):
            pct = np.abs((a[:, None] - a[None, :]) / a[None, :] * 100).ravel()
        a = np.concatenate([a, diff, pct[np.isfinite(pct)]])
    return np.unique(a)


def check(answer: str, results: list[dict], question: str = "") -> tuple[list[Figure], list[Figure]]:
    """Split the answer's figures into (supported, unsupported)."""
    cands = candidates(results, question)
    ok, bad = [], []
    for f in extract(answer):
        target = abs(f.value)
        tol = max(f.tol, target * 5e-4)
        if len(cands) and np.any(np.abs(cands - target) <= tol):
            ok.append(f)
        else:
            bad.append(f)
    return ok, bad
