"""Grounding check: every figure in an answer must come from a tool result.

A figure is *supported* when it matches, at the precision it is written with,
either

  1. a number in the tool results (direct), or
  2. a difference or % change between two numbers that sit in the SAME tool
     object (derived), e.g. a KPI's value and its comparison value, our ASP and
     the rivals' ASP in one sub-category, a cause's current and previous level.

and its unit agrees: a money figure (₹, L, Cr) never matches a percentage
field and a percentage (%, pp, percent) never matches a money field.

Why "same object": the first version allowed a difference or % change between
ANY two numbers in all the results. A diagnostics result holds ~170 numbers, so
that made ~14,000 candidates and 93% of randomly invented percentages "passed".
Restricting derivations to siblings keeps the arithmetic an analyst actually does
(this period vs last, us vs them) and rejects coincidences. See
llm/eval/verifier_eval.py and reports/verifier_eval.md for the measurement.

Precision: "₹40.7 L" means ₹40,70,000 ± ₹5,000; "-2.6%" means 2.55 to 2.65
(sign-insensitive, because "down 2.6%" is how people write a negative change).
Numbers the user typed in the question may be echoed back (direct match only).

Ignored: dates, years, product/period labels (Variant 3, Q2, Tier1, R30) and
small whole numbers without a unit (counts like "5 variants"). Numbers written
as words ("two percent") are not detected: a known limitation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

SCALE = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
         "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
MONEY_SUFFIX = {"cr", "crore", "crores", "l", "lakh", "lakhs", "lac", "k", "thousand", "m", "mn", "million"}
PCT_SUFFIX = {"%", "pp", "percent", "per cent", "percentage point", "percentage points"}
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
    r"\s*(?P<suf>crores?|cr|lakhs?|lac|l|k|thousand|mn|million|m|%|pp|percentage points?|per\s?cent|×|x|★|stars?)?(?![a-z])",
    re.I)

# unit classes: "money", "pct", or "any" (a count, a rating, an index, or a field we can't classify)
# Conservative on purpose: a key we are not sure about is "any" (matches either unit), so the unit
# rule only rejects clear mismatches. ("margin" is "any": it is ₹ in a KPI card but % in health scores.)
PCT_KEY = re.compile(r"(?:pct|_pp$|^pp$|percent|share(?!d)|gap|_rate|rate$|lift|growth)", re.I)
MONEY_KEY = re.compile(r"(?:revenue|asp$|spend|cost|impact|effect$|^change$|^discount_value|rupee)", re.I)
UNIT_CLASS = {"currency": "money", "pct": "pct"}  # the registry's KPI units


@dataclass
class Figure:
    text: str
    value: float
    tol: float
    unit: str

    @property
    def kind(self) -> str:
        if self.unit == "₹" or self.unit in MONEY_SUFFIX:
            return "money"
        if self.unit in PCT_SUFFIX or self.unit.startswith("per"):
            return "pct"
        return "any"


def extract(text: str) -> list[Figure]:
    t = text
    for pat in STRIP:
        t = re.sub(pat, " ", t, flags=re.I)
    out = []
    for m in NUM.finditer(t):
        raw = m.group("num")
        suf = re.sub(r"\s+", " ", (m.group("suf") or "").lower())
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
        unit = suf or ("₹" if cur else "")
        if suf == "per cent":
            unit = "percent"
        out.append(Figure(m.group(0).strip(), v * scale, max(tol, 1e-9), unit))
    return out


# ------------------------------------------------------------------------------------------ facts
# keys whose string value names the entity an object is about
LABEL_KEYS = {"brand", "retailer", "region", "channel", "tier", "subcategory", "variant", "productname",
              "manufacturer", "competitor", "name"}
ROOT_GROUP = 0  # the top-level numbers of every tool result: lets "Dettol 24.49% vs Lifebuoy 19.96% (4.53 pp)" through


@dataclass
class Fact:
    value: float   # absolute value
    kind: str      # money | pct | any
    group: int     # id of the tool object the number sits in (siblings share it)
    labels: frozenset = frozenset()  # entity names (brand, retailer, variant...) of this object and its parents


def _key_kind(key: str, obj_unit: str | None) -> str:
    k = str(key)
    if obj_unit in UNIT_CLASS and k in ("value", "comparison_value", "current", "previous", "delta", "share"):
        return UNIT_CLASS[obj_unit]
    if k in ("change_pct", "change_pp", "delta_pct"):
        return "pct"
    if PCT_KEY.search(k):
        return "pct"
    if MONEY_KEY.search(k):
        return "money"
    return "any"


def facts(results: list[dict]) -> list[Fact]:
    out: list[Fact] = []
    counter = [0]

    def own_labels(o: dict) -> set:
        return {v.lower() for k, v in o.items() if isinstance(v, str) and k.lower() in LABEL_KEYS}

    def walk(o, key="", kind_hint="any", group=-2, labels=frozenset()):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            out.append(Fact(abs(float(o)), kind_hint, group, labels))
        elif isinstance(o, str):  # figures quoted inside tool text (cause descriptions, headlines, definitions)
            for f in extract(o):
                out.append(Fact(abs(f.value), f.kind, group, labels))
        elif isinstance(o, dict):
            counter[0] += 1
            g = counter[0]
            unit = o.get("unit") if isinstance(o.get("unit"), str) else None
            lab = labels | own_labels(o)
            for k, v in o.items():
                walk(v, k, _key_kind(k, unit), g, lab)
        elif isinstance(o, (list, tuple)):
            out.append(Fact(float(len(o)), "any", group, labels))  # "3 rivals", "27 complaints"
            for v in o:
                walk(v, key, kind_hint, group, labels)

    for r in results:
        if isinstance(r, dict):
            counter[0] += 1
            g = counter[0]
            unit = r.get("unit") if isinstance(r.get("unit"), str) else None
            lab = frozenset(own_labels(r))
            for k, v in r.items():
                kind = _key_kind(k, unit)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(Fact(abs(float(v)), kind, g, lab))
                    out.append(Fact(abs(float(v)), kind, ROOT_GROUP, lab))
                else:
                    walk(v, k, kind, g, lab)
        else:
            walk(r)
    return out


def _compatible(fig_kind: str, fact_kind: str) -> bool:
    return fig_kind == "any" or fact_kind == "any" or fig_kind == fact_kind


def _derived(fs: list[Fact]) -> list[Fact]:
    """Differences and % changes between two numbers in the same object."""
    by_group: dict[int, list[Fact]] = {}
    for f in fs:
        by_group.setdefault(f.group, []).append(f)
    out = []
    for g, items in by_group.items():
        if len(items) < 2 or len(items) > 80:  # a huge flat object would bring back the combinatorial problem
            continue
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if not _compatible(a.kind, b.kind):
                    continue
                kind = a.kind if a.kind != "any" else b.kind
                lab = a.labels | b.labels
                out.append(Fact(abs(a.value - b.value), kind, g, lab))  # a difference keeps the unit (₹ or pp)
                for x, y in ((a, b), (b, a)):
                    if y.value:
                        out.append(Fact(abs((x.value - y.value) / y.value * 100), "pct", g, lab))
    return out


def _supported(f: Figure, pool: list[Fact]) -> bool:
    target, tol = abs(f.value), max(f.tol, abs(f.value) * 5e-4)
    return any(abs(c.value - target) <= tol and _compatible(f.kind, c.kind) for c in pool)


def _entities(pool: list[Fact]) -> set[str]:
    return {lab for f in pool for lab in f.labels}


def _named(sentence: str, entities: set[str]) -> set[str]:
    s = sentence.lower()
    return {e for e in entities if len(e) > 2 and re.search(rf"(?<![a-z0-9]){re.escape(e)}(?![a-z0-9])", s)}


def check(answer: str, results: list[dict], question: str = "",
          entities: set[str] | None = None) -> tuple[list[Figure], list[Figure]]:
    """Split the answer's figures into (supported, unsupported).

    Entity binding (when `entities` is given: the data's brand, retailer, variant, region... names):
    if a sentence names entities that label tool objects, its figures must come from objects about one
    of them (or from objects with no label). "Veet's health score is 57" fails when 57 is Lux's score."""
    direct = facts(results)
    pool = direct + _derived(direct)
    asked = [Fact(abs(q.value), "any", -1) for q in extract(question)]
    vocab = {e.lower() for e in (entities or ())}
    entities = _entities(pool) & vocab
    ok, bad = [], []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", answer):
        named = _named(sentence, entities)
        scoped = [c for c in pool if not c.labels or c.labels & named] if named else pool
        for f in extract(sentence):
            (ok if _supported(f, scoped + asked) else bad).append(f)
    return ok, bad


def candidates(results: list[dict], extra_text: str = "") -> np.ndarray:
    """All values a figure could match (for inspection and the evaluation)."""
    direct = facts(results)
    vals = [c.value for c in direct + _derived(direct)] + [f.value for f in extract(extra_text)]
    return np.unique(np.array(vals, dtype=float)) if vals else np.array([])
