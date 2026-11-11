"""Grounded Q&A assistant.

Flow for every question
  1. The LLM (Gemini or Ollama) sees the question, the dashboard context
     (brand, period, comparison) and the tool list. It never sees raw data.
  2. It calls tools; arguments are validated, the KPI engine computes.
  3. It writes an answer from the tool results only.
  4. The verifier checks every figure in the answer against the tool results.
     One retry with the unsupported figures named; if it still fails, the
     unsupported sentences are dropped (or the deterministic answer is used).

Offline mode (no LLM) routes questions to tools by keyword and fills
templates. It is also the fallback when the LLM is unreachable.
"""
from __future__ import annotations

import json
import re
import time

from api.service import Service
from kpi import registry as R
from pipeline.schema import CORE_BRANDS

from . import verifier
from .client import ChatClient, LLMError
from .config import Settings, settings
from .tools import Toolbox

MAX_ROUNDS = 5

SYSTEM = """You are BrandPulse, an analyst assistant for Reckitt brand managers.
Core (Reckitt) brands: Dettol, Harpic, Veet, Mortein, Lizol. Competitor brands: Ariel, Domex, Gillette, Head & Shoulders, Lifebuoy, Lux (Unilever and P&G).
A core brand's competitors are the external SKUs in the same sub-categories it sells in.

Rules
- Every number you state must come from a tool result in this conversation. Never estimate, extrapolate or recall numbers.
- Always call a tool before answering a question about performance, even if you think you know the answer.
- You may round, and you may take a difference or % change between two tool numbers; nothing else.
- Write money in Indian style: ₹ with L (lakh = 1,00,000) or Cr (crore = 1,00,00,000), e.g. ₹40.7 L. Percent changes of percentages are in pp.
- Say which period and comparison the numbers are for.
- If a tool says available=false, or the data does not cover the question (e.g. market share for Lizol or Mortein,
  campaign spend for a single brand), say so plainly and offer the closest thing the data does have. Do not guess.
- For "why" questions use explain_change; for definitions, rules and caveats use search_knowledge.
- Keep answers short: 2 to 6 sentences, or a short list. Plain text only: no markdown, no ** or #, no tables;
  for a list start each line with "• ".
"""


def _ctx_line(brand, period, mode) -> str:
    return (f"Dashboard context: brand={brand}, period={period}, comparison={'same period last year' if mode == 'yoy' else 'previous period'}. "
            "Use these unless the question names something else. Data ends 30 Dec 2025.")


# ---------------------------------------------------------------------------------------- offline
PERIOD_WORDS = [
    (r"\blast\s+13\s+weeks|\bl13w", "L13W"), (r"\blast\s+90\s+days|\brolling\s+90|\br90\b", "R90"),
    (r"\blast\s+30\s+days|\brolling\s+30|\br30\b", "R30"), (r"\blast\s+7\s+days|\blast\s+week\b|\br7\b", "R7"),
    (r"\bthis\s+month|\bmtd\b|month\s+to\s+date", "MTD"), (r"\bthis\s+quarter|\bqtd\b|quarter\s+to\s+date", "QTD"),
    (r"\blast\s+month|\bprevious\s+month", "PM"), (r"\blast\s+quarter|\bprevious\s+quarter", "PQ"),
    (r"\bthis\s+week|\bwtd\b|week\s+to\s+date", "WTD"), (r"\b(?:in|during|for|over)\s+(?:last year|2024)\b|\bprevious year\b", "PY"),
    (r"\bytd\b|this\s+year|year\s+to\s+date|\b2025\b", "YTD"), (r"\ball\s+(?:time|data)|two\s+years", "ALL"),
]
KPI_WORDS = [
    (r"growth|grow|grew", "revenue_growth_pct"), (r"\bunits?\b|volume", "units"), (r"\basp\b|average selling price|selling price", "asp"),
    (r"gross margin|margin value|margin in (?:rupees|₹)|profit", "margin"), (r"margin", "margin_pct"), (r"discount", "discount_pct"),
    (r"promo(?:tion)?s?\s+lift", "promo_lift_pct"), (r"promo", "promo_revenue_share"), (r"rating|review", "avg_rating"),
    (r"leak", "leakage_complaint_pct"), (r"stock", "stockout_risk_pct"), (r"market share", "market_share"),
    (r"campaign spend|marketing spend|\bspend\b", "campaign_spend"), (r"\broi\b|return on", "campaign_roi"),
    (r"price index", "price_index"), (r"premium|tier.?1 share", "tier1_revenue_share"), (r"revenue|sales|turnover", "revenue"),
]
DIM_WORDS = [(r"retailer", "Retailer"), (r"region", "Region"), (r"channel", "Channel"), (r"sub.?categor", "SubCategory"),
             (r"variant|sku|product", "Variant"), (r"categor", "Category")]
SUBCATS = ["Cleaner", "Cream", "Liquid", "Soap", "Spray"]


def _fmt(unit, v):
    if v is None:
        return "not available"
    if unit == "currency":
        a = abs(v)
        s = f"₹{a / 1e7:.2f} Cr" if a >= 1e7 else f"₹{a / 1e5:.1f} L" if a >= 1e5 else f"₹{a:,.1f}"
        return ("-" if v < 0 else "") + s
    if unit == "pct":
        return f"{v:.1f}%"
    if unit == "rating":
        return f"{v:.2f} out of 5"
    if unit == "ratio":
        return f"{v:.2f}x"
    return f"{v:,.1f}" if abs(v) < 1000 else f"{v:,.0f}"


def _chg(v, unit="%"):
    if v is None:
        return "with no comparison available"
    word = "up" if v > 0 else "down" if v < 0 else "flat"
    return f"{word} {abs(v):.1f}{unit}"


class Offline:
    """Deterministic keyword router + templates. Never invents a number: everything is a tool result."""

    def __init__(self, tools: Toolbox):
        self.t = tools

    def plan(self, q: str, brand: str, period: str, mode: str) -> tuple[str, dict]:
        ql = q.lower()
        for b in self.t.brands:
            if re.search(rf"\b{re.escape(b.lower())}\b", ql):
                brand = b
                break
        for pat, p in PERIOD_WORDS:
            if re.search(pat, ql):
                period = p
                break
        if re.search(r"previous (?:period|month|quarter)|vs\.? last month|month on month|mom\b", ql):
            mode = "previous"
        elif re.search(r"last year|year on year|yoy|same period", ql):
            mode = "yoy"
        sub = next((s for s in SUBCATS if s.lower() in ql), None)
        core = brand if brand in CORE_BRANDS else None

        if re.search(r"\bforecast|\bpredict|\bwill\b.*\bbe\b|next (?:month|quarter|year|week)|projection", ql):
            return "_refuse", {"reason": "The data has no forecasts: it records what happened from 1 Jan 2024 to 30 Dec 2025."}
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", ql)]
        if any(y not in (2024, 2025) for y in years):
            return "_refuse", {"reason": "The data only covers 1 Jan 2024 to 30 Dec 2025."}
        mv = re.search(r"variant\s*(\d)", ql)
        if core and mv and re.search(r"compet|rival", ql):
            return "get_variants", {"brand": core, "period": period, "mode": mode, "_variant": f"{core} Variant {mv.group(1)}"}
        if core and re.search(r"market share gap|share gap", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "share_gap"}

        if re.search(r"\bwhy\b|explain|reason|what (?:drove|caused)|declin|dropp|fell|went down", ql) and core:
            return "explain_change", {"brand": core, "period": period, "mode": mode, **({"subcategory": sub} if sub else {})}
        if re.search(r"how (?:is|are|do you|does) .*(?:calculat|measur|defin|comput|match|scor)|what does .* mean|\bdefin|\bformula|"
                     r"why (?:is|are|does|do) .*(?:\bno\b|missing|not available|n/a)|caveat|\brules?\b|what is (?:a|an|the) [a-z ]*(?:index|score|lift)\b", ql):
            return "search_knowledge", {"query": q}
        if re.search(r"health", ql):
            return "get_health_scores", {"period": period}
        if core and re.search(r"discounting|who .*discount|competitor discount", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "discount"}
        if core and re.search(r"gain(?:ed)? .*share|share gain|lost share|who .*share", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "share"}
        if core and re.search(r"launch", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "launch"}
        if core and re.search(r"price gap|cheaper|more expensive|price position|competitor price", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "price", "_sub": sub}
        if core and re.search(r"closest rival|biggest (?:rival|competitor|threat)|who (?:are|is) (?:our|the)? ?compet|rivals?\b", ql):
            return "get_competitors", {"brand": core, "period": period, "mode": mode, "_focus": "rivals"}
        kpi = next((k for pat, k in KPI_WORDS if re.search(pat, ql)), "revenue")
        dim = next((d for pat, d in DIM_WORDS if re.search(pat, ql)), None)
        if dim and dim != "SubCategory" or (dim == "SubCategory" and not sub):
            return "get_breakdown", {"kpi": kpi, "by": dim, "brand": brand, "period": period, "mode": mode,
                                     "_rank": "low" if re.search(r"lowest|worst|least|smallest", ql) else "high"}
        return "get_kpi", {"kpi": kpi, "brand": brand, "period": period, "mode": mode, **({"subcategory": sub} if sub else {})}

    def answer(self, name: str, args: dict, res: dict) -> str:
        if name == "_refuse":
            return res["reason"]
        if "error" in res:
            return f"I couldn't compute that: {res['error']}"
        if res.get("available") is False:
            return f"The data doesn't cover this: {res.get('reason', '')}"
        if name == "get_kpi":
            per = res["period"]
            cmp_ = res.get("comparison_period")
            if res["kpi"] in ("revenue_growth_pct", "unit_growth_pct"):
                return (f"{res['brand']} {res['name'].lower()} for {per['label'].lower()} ({per['start']} to {per['end']}) is "
                        f"{res['value']:+.1f}% vs {cmp_['label'].lower()}.")
            ch = res.get("change_pp", res.get("change_pct"))
            unit = "pp" if "change_pp" in res else "%"
            txt = (f"{res['brand']} {res['name'].lower()} for {per['label'].lower()} ({per['start']} to {per['end']}) is "
                   f"{_fmt(res['unit'], res['value'])}, {_chg(ch, unit)} vs {cmp_['label'].lower() if cmp_ else 'no comparison'}"
                   f"{' (' + _fmt(res['unit'], res['comparison_value']) + ')' if res.get('comparison_value') is not None else ''}.")
            return txt + (f" Note: {res['note']}" if res.get("note") else "")
        if name == "get_breakdown":
            rows = [r for r in res["rows"] if r["value"] is not None]
            if not rows:
                return "No data for that breakdown."
            rows = sorted(rows, key=lambda r: r["value"], reverse=args.get("_rank") != "low")
            top = rows[0]
            lines = [f"{r[res['by']]}: {_fmt(res['unit'], r['value'])} ({_chg(r.get('change_pct'))})" for r in rows[:5]]
            return (f"For {res['brand']}, {res['period']['label'].lower()}, the {'lowest' if args.get('_rank') == 'low' else 'highest'} "
                    f"{res['name'].lower()} by {res['by'].lower()} is {top[res['by']]} at {_fmt(res['unit'], top['value'])}.\n"
                    + "\n".join("• " + x for x in lines))
        if name == "get_competitors":
            f = args.get("_focus")
            b = res["brand"]
            if f == "discount":
                d = res["who_is_discounting"]
                return (f"In {b}'s sub-categories, {d[0]['brand']} discounts the most ({d[0]['discount_pct']:.2f}% off MRP, "
                        f"{_chg(d[0]['change_pp'], 'pp')}). {b} itself averages {res['our_discount_pct']:.2f}%. Others: "
                        + ", ".join(f"{x['brand']} {x['discount_pct']:.2f}%" for x in d[1:]) + ".")
            if f == "share":
                s = res["share_of_subcategory_change"]
                ms = res["market_share"]
                extra = ""
                if ms["available"] and ms["rivals"]:
                    extra = " Reported market share change: " + ", ".join(f"{r['brand']} {r['change_pp']:+.2f}pp" for r in ms["rivals"]) + "."
                return (f"{s[0]['Brand']} gained the most share of {b}'s sub-categories ({s[0]['change_pp']:+.1f}pp of sub-category "
                        f"revenue among the 11 tracked brands). Lowest: {s[-1]['Brand']} ({s[-1]['change_pp']:+.1f}pp).{extra}")
            if f == "share_gap":
                ms = res["market_share"]
                if not ms["available"]:
                    return f"The data doesn't cover this: {ms['note']}"
                return (f"{b}'s market share is {ms['our_share']:.2f}%. Gap vs rivals with share data: "
                        + ", ".join(f"{r['brand']} {r['share']:.2f}% (gap {r['gap_pp']:+.2f}pp)" for r in ms["rivals"]) + ".")
            if f == "launch":
                ls = res["competitor_launches"]
                if not ls:
                    return f"No competitor launches by {b}'s rival manufacturers in this period."
                return (f"{len(ls)} launch{'es' if len(ls) > 1 else ''} by {b}'s rival manufacturers in this period: "
                        + ", ".join(f"{e['competitor']} on {e['date']}" for e in ls) + ". Events are recorded per manufacturer, not per brand.")
            if f == "price":
                rows = res["price_by_subcategory"]
                if args.get("_sub"):
                    rows = [r for r in rows if r["SubCategory"] == args["_sub"]] or rows
                return (f"{b}'s overall price gap vs external rivals is {res['price_gap_pct']:+.1f}% (negative = cheaper). By sub-category: "
                        + "; ".join(f"{r['SubCategory']} ₹{r['our_asp']:.1f} vs ₹{r['rival_asp']:.1f} ({r['price_gap_pct']:+.1f}%)" for r in rows) + ".")
            cr = res["closest_rivals"]
            return (f"{b}'s closest external rival is {cr[0]['brand']} ({cr[0]['manufacturer']}), competing with {cr[0]['variants_overlapped']} "
                    f"of {cr[0]['of_variants']} variants. Ranking: " + ", ".join(f"{r['brand']} {r['variants_overlapped']}/{r['of_variants']}" for r in cr) + ".")
        if name == "get_variants":
            v = next((x for x in res["variants"] if x["variant"].lower() == args.get("_variant", "").lower()), None)
            if not v:
                return f"No such variant. {res['brand']} variants: " + ", ".join(x["variant"] for x in res["variants"]) + "."
            return (f"{v['variant']} ({v['subcategory']}) competes with external brands {', '.join(v['external_rival_brands'])}"
                    + (f" and with Reckitt's {', '.join(v['other_reckitt_rivals'])}" if v["other_reckitt_rivals"] else "")
                    + f" in the {v['subcategory']} sub-category.")
        if name == "explain_change":
            causes = [c for c in res["causes"] if c["supporting"]]
            txt = res["headline"]
            br = {b["name"]: b["value"] for b in res["bridge"]}
            txt += (f" Bridge: volume {_fmt('currency', br.get('Volume'))}, mix {_fmt('currency', br.get('Mix'))}, "
                    f"price/discount {_fmt('currency', br.get('Price / discount'))}.")
            if causes:
                txt += " Supporting causes: " + " ".join(f"{c['title']}: {c['text']}" for c in causes[:3])
            return txt
        if name == "get_health_scores":
            core = [r for r in res["brands"] if r["IsCore"]]
            return ("Brand Health Score (" + res["period"]["label"].lower() + "): "
                    + ", ".join(f"{r['Brand']} {r['health_score']:.0f} (rank {r['rank']}{', proxy position' if r['position_source'] == 'proxy' else ''})" for r in core) + ".")
        if name == "search_knowledge":
            return "\n".join(f"• {r['text']}" for r in res["results"][:3])
        return json.dumps(res)[:500]


# ---------------------------------------------------------------------------------------- assistant
class Assistant:
    def __init__(self, service: Service | None = None, cfg: Settings | None = None):
        self.cfg = cfg or settings()
        self.tools = Toolbox(service)
        self.offline = Offline(self.tools)
        self.client = (ChatClient(self.cfg.base_url, list(self.cfg.models), self.cfg.api_key)
                       if self.cfg.provider in ("gemini", "ollama") else None)

    def status(self) -> dict:
        return {"provider": self.cfg.provider, "model": self.client.model if self.client else None,
                "models": list(self.cfg.models), "exhausted": sorted(self.client.exhausted) if self.client else [],
                "ready": self.cfg.ready or self.cfg.provider == "offline", "retrieval": self.tools.kb.mode}

    # -------------------------------------------------------------- offline path
    def _offline(self, question, brand, period, mode, reason=None) -> dict:
        name, args = self.offline.plan(question, brand, period, mode)
        call = {k: v for k, v in args.items() if not k.startswith("_")}
        if name == "_refuse":
            return {"answer": args["reason"], "provider": "offline" + (f" (fallback: {reason})" if reason else ""),
                    "model": None, "tool_calls": [], "verified": True, "figures": 0, "unsupported_draft": [], "refused": True}
        res = self.tools.run(name, call)
        text = self.offline.answer(name, args, res)
        ok, bad = verifier.check(text, [res], question)
        return {"answer": text, "provider": "offline" + (f" (fallback: {reason})" if reason else ""), "model": None,
                "tool_calls": [{"name": name, "args": call}], "verified": not bad, "figures": len(ok) + len(bad),
                "unsupported_draft": [f.text for f in bad], "refused": res.get("available") is False or "error" in res}

    # -------------------------------------------------------------- LLM path
    def ask(self, question: str, brand: str = "Dettol", period: str = "YTD", mode: str = "yoy",
            history: list[dict] | None = None) -> dict:
        t0 = time.time()
        if self.client is None:
            out = self._offline(question, brand, period, mode)
            return {**out, "seconds": round(time.time() - t0, 2)}
        msgs = [{"role": "system", "content": SYSTEM + "\n" + _ctx_line(brand, period, mode)}]
        for h in (history or [])[-6:]:
            if h.get("text"):
                msgs.append({"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]})
        msgs.append({"role": "user", "content": question})
        calls, results = [], []
        try:
            text = self._loop(msgs, calls, results)
            ok, bad = verifier.check(text, results, question)
            draft_bad = [f.text for f in bad]
            draft_figures = len(ok) + len(bad)
            if bad:  # one retry, naming the problem figures
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "user", "content":
                             f"These figures are not in any tool result: {', '.join(draft_bad)}. Rewrite the answer using only "
                             "numbers from the tool results (call another tool if you need a number). Do not mention this check."})
                text = self._loop(msgs, calls, results)
                ok, bad = verifier.check(text, results, question)
            verified = not bad
            if bad:  # drop the sentences that still carry unsupported figures
                sentences = re.split(r"(?<=[.!?])\s+", text)
                keep = [s for s in sentences if not any(f.text in s for f in bad)]
                text = " ".join(keep).strip()
                if not text:
                    out = self._offline(question, brand, period, mode, reason="answer could not be verified")
                    return {**out, "unsupported_draft": draft_bad, "seconds": round(time.time() - t0, 2)}
                text += "\n\n(Some figures were removed because they could not be traced to the data.)"
            refused = any(r.get("available") is False for r in results) or not results
            return {"answer": text, "provider": self.cfg.provider, "model": self.client.last_model, "tool_calls": calls,
                    "verified": verified, "figures": draft_figures, "unsupported_draft": draft_bad, "refused": refused,
                    "seconds": round(time.time() - t0, 2)}
        except LLMError as e:
            out = self._offline(question, brand, period, mode, reason=f"{self.cfg.provider} unavailable")
            return {**out, "error": str(e)[:200], "seconds": round(time.time() - t0, 2)}

    def _loop(self, msgs, calls, results) -> str:
        for _ in range(MAX_ROUNDS):
            m = self.client.chat(msgs, self.tools.specs)
            tcs = m.get("tool_calls") or []
            msgs.append({k: v for k, v in m.items() if v is not None})
            if not tcs:
                return (m.get("content") or "").strip()
            for tc in tcs:
                fn = tc["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                res = self.tools.run(fn["name"], args)
                calls.append({"name": fn["name"], "args": args})
                results.append(res)
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", fn["name"]), "name": fn["name"],
                             "content": self.tools.dumps(res)})
        msgs.append({"role": "user", "content": "Answer now from the tool results you have."})
        m = self.client.chat(msgs, None)
        return (m.get("content") or "").strip()

    # -------------------------------------------------------------- diagnostics narrative
    def explain(self, brand: str, period: str = "MTD", mode: str = "yoy", subcategory: str | None = None) -> dict:
        args = {"brand": brand, "period": period, "mode": mode, **({"subcategory": subcategory} if subcategory else {})}
        res = self.tools.run("explain_change", args)
        fallback = self.offline.answer("explain_change", args, res)
        if self.client is None or "error" in res or res.get("available") is False:
            return {"answer": fallback, "provider": "offline", "verified": True, "tool_calls": [{"name": "explain_change", "args": args}]}
        prompt = ("Explain this revenue change to a brand manager in 4 to 6 plain sentences: what happened, the biggest driver "
                  "in the bridge, which supporting causes explain it (and which checked causes did not), and where it happened "
                  "(SKUs/retailers/regions). Use only numbers in the JSON. Money in ₹ lakh (L).\n\n" + self.tools.dumps(res))
        try:
            m = self.client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
            text = (m.get("content") or "").strip()
            ok, bad = verifier.check(text, [res])
            if bad:
                return {"answer": fallback, "provider": "offline (LLM narrative failed verification)", "verified": True,
                        "unsupported_draft": [f.text for f in bad], "tool_calls": [{"name": "explain_change", "args": args}]}
            return {"answer": text, "provider": f"{self.cfg.provider} · {self.client.last_model}", "verified": True,
                    "tool_calls": [{"name": "explain_change", "args": args}]}
        except LLMError as e:
            return {"answer": fallback, "provider": "offline (LLM unavailable)", "verified": True, "error": str(e)[:200]}
