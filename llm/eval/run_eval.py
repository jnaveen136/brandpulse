"""Run the Q&A evaluation and write reports/llm_eval.json (+ .md).

    python -m llm.eval.run_eval                 # provider from .env / LLM_PROVIDER
    python -m llm.eval.run_eval --limit 15      # stay inside a free-tier daily quota
    python -m llm.eval.run_eval --fresh         # ignore saved answers

Answers are saved per provider in reports/llm_eval_runs/<provider>.jsonl and
reused on the next run, so a free-tier evaluation can be finished over
several days. Metrics:

  accuracy        the expected number (within the answer's own rounding) or all
                  expected words appear in the answer; refusal items count as
                  correct when the answer says the data does not cover it
  unsupported     share of figures in first drafts that no tool result
                  supports (what the verifier catches before the user sees it)
  final verified  share of answers whose final text passed the verifier
"""
from __future__ import annotations

import argparse
import json
import sys
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from llm.assistant import Assistant
from llm.verifier import extract

from .questions import QUESTIONS

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "reports" / "llm_eval_runs"
REFUSAL = re.compile(r"not available|isn.t available|no (?:market.share )?data|doesn.t (?:cover|have|track|include)|"
                     r"does not (?:cover|have|track|include)|not (?:tracked|recorded|covered|provided)|only available|"
                     r"company.wide|can.?not (?:forecast|predict|provide)|can.t (?:forecast|predict|provide)|"
                     r"unable to|no forecast|starts? (?:on|in|from) (?:1 jan|jan)|not possible|only (?:has|covers|includes)", re.I)


def score(item, ans: dict, expected: dict) -> tuple[bool, str]:
    text = ans["answer"]
    if item.get("refuse"):
        ok = bool(REFUSAL.search(text))
        return ok, "refused" if ok else "did not say the data is missing"
    if "texts" in expected and expected["texts"]:
        missing = [t for t in expected["texts"] if t.lower() not in text.lower()]
        if not missing:
            return True, "all expected words present"
        if "numbers" not in expected:
            return False, f"missing: {', '.join(missing)}"
    figs = extract(text)
    for target in expected.get("numbers", []):
        for f in figs:
            if abs(abs(f.value) - abs(target)) <= max(f.tol, abs(target) * 0.005):
                return True, f"found {f.text} for {target:,.2f}"
    return False, f"expected one of {[round(x, 2) for x in expected.get('numbers', [])]}, figures in answer: {[f.text for f in figs][:8]}"


def main() -> None:
    # Windows consoles/pipes may not be UTF-8: never crash on a ★ or ₹ in a message
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="answer at most N new questions this run")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between questions (rate limits)")
    args = ap.parse_args()

    a = Assistant()
    a.tools.kb.wait(600)  # evaluate with the full hybrid retrieval, not the keyword-only start-up mode
    provider = a.cfg.provider
    RUNS.mkdir(parents=True, exist_ok=True)
    store = RUNS / f"{provider}.jsonl"
    saved = {}
    if store.exists() and not args.fresh:
        for line in store.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            saved[r["q"]] = r
    elif args.fresh and store.exists():
        store.unlink()

    new = 0
    for item in QUESTIONS:
        if item["q"] in saved:
            continue
        if args.limit is not None and new >= args.limit:
            break
        ans = a.ask(item["q"], item["brand"], item["period"], item["mode"])
        if provider != "offline" and ans["provider"].startswith("offline"):
            print(f"stopping: {provider} unavailable ({ans.get('error', '')[:120]})")
            break
        rec = {"q": item["q"], "kind": item["kind"], "answer": ans["answer"], "provider": ans["provider"],
               "model": ans.get("model"), "tool_calls": ans["tool_calls"], "verified": ans["verified"],
               "figures": ans.get("figures", 0), "unsupported_draft": ans.get("unsupported_draft", []),
               "seconds": ans.get("seconds")}
        saved[item["q"]] = rec
        with store.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        new += 1
        print(f"[{new}] {item['kind']:<10} {item['q'][:70]}")
        if args.sleep:
            time.sleep(args.sleep)

    results = []
    for item in QUESTIONS:
        if item["q"] not in saved:
            continue
        rec = saved[item["q"]]
        ok, why = score(item, rec, item["expect"](a.tools))
        results.append({**rec, "correct": ok, "why": why})
    n = len(results)
    if not n:
        print("No answers yet.")
        return
    figs = sum(r["figures"] for r in results)
    bad = sum(len(r["unsupported_draft"]) for r in results)
    refusals = [r for r in results if r["kind"] == "refusal"]
    answered = [r for r in results if r["kind"] != "refusal"]
    by_kind = {}
    for r in results:
        k = by_kind.setdefault(r["kind"], [0, 0])
        k[0] += r["correct"]
        k[1] += 1
    summary = {
        "provider": provider + (f" ({', '.join(sorted({r['model'] for r in results if r.get('model')}))})" if provider != "offline" else ""),
        "questions": n, "of_total": len(QUESTIONS),
        "accuracy_pct": 100 * sum(r["correct"] for r in results) / n,
        "answer_accuracy_pct": 100 * sum(r["correct"] for r in answered) / max(len(answered), 1),
        "refusal_accuracy_pct": 100 * sum(r["correct"] for r in refusals) / max(len(refusals), 1),
        "figures_in_drafts": figs, "unsupported_in_drafts": bad,
        "hallucination_rate_pct": 100 * bad / max(figs, 1),
        "final_verified_pct": 100 * sum(r["verified"] for r in results) / n,
        "by_kind": {k: f"{c}/{t}" for k, (c, t) in by_kind.items()},
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    out = ROOT / "reports" / ("llm_eval.json" if provider != "offline" else "llm_eval_offline.json")
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# Q&A evaluation · {summary['provider']}", "",
             f"{n} of {len(QUESTIONS)} questions · run {summary['run_at']}", "",
             "| Metric | Value |", "|---|---|",
             f"| Accuracy (all) | {summary['accuracy_pct']:.0f}% |",
             f"| Accuracy (answerable questions) | {summary['answer_accuracy_pct']:.0f}% |",
             f"| Correct refusals | {summary['refusal_accuracy_pct']:.0f}% |",
             f"| Unsupported figures in first drafts | {bad} of {figs} ({summary['hallucination_rate_pct']:.1f}%) |",
             f"| Final answers fully verified | {summary['final_verified_pct']:.0f}% |", "",
             "By kind: " + ", ".join(f"{k} {v}" for k, v in summary["by_kind"].items()), "",
             "| ✓ | Kind | Question | Why |", "|---|---|---|---|"]
    lines += [f"| {'✅' if r['correct'] else '❌'} | {r['kind']} | {r['q']} | {r['why']} |" for r in results]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
