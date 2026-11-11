"""Q&A layer tests. No network: the LLM is replaced by a scripted fake."""
import json

import pytest

from llm import verifier
from llm.assistant import Assistant
from llm.config import Settings


@pytest.fixture(scope="module")
def offline():
    return Assistant(cfg=Settings("offline", None, (), None, None))


# ---------------------------------------------------------------- verifier
def test_verifier_accepts_rounded_indian_units():
    res = [{"value": 4067007.75, "comparison_value": 4177388.75, "change_pct": -2.64}]
    ok, bad = verifier.check("Revenue was ₹40.7 L, down 2.6% from ₹41.8 L (a ₹1.1 L drop). ₹0.41 Cr.", res)
    assert not bad and len(ok) == 5


def test_verifier_rejects_invented_figures():
    ok, bad = verifier.check("Revenue was ₹45.2 L, up 3.1%.", [{"value": 4067007.75, "change_pct": -2.64}])
    assert [f.text for f in bad] == ["₹45.2 L", "3.1%"]


def test_verifier_ignores_dates_labels_and_counts():
    ok, bad = verifier.check("Between 1 Jan 2025 and 30 Dec 2025, Dettol Variant 3 in Q2 faced 5 rivals (YTD, Tier1, R30).", [{}])
    assert not ok and not bad


def test_verifier_respects_displayed_precision():
    res = [{"v": 24.4858}]
    assert not verifier.check("24.49%", res)[1]
    assert verifier.check("24.6%", res)[1]  # 24.6 can't be a rounding of 24.4858


# ---------------------------------------------------------------- tools
def test_tool_validation_errors_are_returned_not_raised(offline):
    t = offline.tools
    assert "Unknown KPI" in t.run("get_kpi", {"kpi": "sales_magic", "brand": "Dettol"})["error"]
    assert "competitor brand" in t.run("get_competitors", {"brand": "Lux"})["error"]
    assert "Unknown period" in t.run("get_kpi", {"kpi": "revenue", "brand": "Dettol", "period": "LAST_DECADE"})["error"]
    assert "Unknown tool" in t.run("drop_tables", {})["error"]


def test_missing_market_share_is_flagged(offline):
    r = offline.tools.run("get_kpi", {"kpi": "market_share", "brand": "Mortein"})
    assert r["available"] is False and "Available for" in r["reason"]


def test_knowledge_search_finds_rules(offline):
    hits = offline.tools.run("search_knowledge", {"query": "how are competitors matched"})["results"]
    assert any("SubCategory" in h["text"] or "sub-categor" in h["text"].lower() for h in hits)


# ---------------------------------------------------------------- offline answers
@pytest.mark.parametrize("q", [
    "What is Dettol's revenue this year?", "Who is discounting most?", "Which retailer has the highest margin?",
    "Why did revenue change last month?", "What is our price gap in Soap?",
])
def test_offline_answers_are_grounded(offline, q):
    r = offline.ask(q, "Dettol", "YTD", "yoy")
    assert r["verified"] and not r["unsupported_draft"] and r["tool_calls"]


def test_offline_refuses_forecasts_and_missing_years(offline):
    assert "no forecasts" in offline.ask("What will revenue be next quarter?", "Dettol")["answer"]
    assert "only covers" in offline.ask("Harpic revenue in 2023?", "Harpic")["answer"]


# ---------------------------------------------------------------- LLM loop with a fake model
class FakeClient:
    """Plays a scripted conversation: one tool call, then a wrong answer, then a corrected one."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        self.model = "fake"
        self.last_model = "fake"
        self.exhausted = set()

    def chat(self, messages, tools=None, temperature=0.1):
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        return self.replies.pop(0)


def _call(name, args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_llm_answer_with_invented_number_is_retried_and_fixed(offline):
    a = Assistant(cfg=Settings("gemini", "fake", ("fake",), "http://x", "k"))
    a.tools, a.offline = offline.tools, offline.offline
    a.client = FakeClient([
        _call("get_kpi", {"kpi": "revenue", "brand": "Dettol", "period": "YTD"}),
        {"role": "assistant", "content": "Dettol revenue was ₹52.0 L this year."},   # invented
        {"role": "assistant", "content": "Dettol revenue was ₹40.7 L this year, down 2.6%."},
    ])
    r = a.ask("What is Dettol revenue?", "Dettol", "YTD", "yoy")
    assert r["unsupported_draft"] == ["₹52.0 L"]
    assert r["verified"] and "₹40.7 L" in r["answer"]
    assert "not in any tool result" in a.client.seen[-1][-1]["content"]


def test_llm_that_keeps_inventing_falls_back_to_grounded_text(offline):
    a = Assistant(cfg=Settings("gemini", "fake", ("fake",), "http://x", "k"))
    a.tools, a.offline = offline.tools, offline.offline
    a.client = FakeClient([
        _call("get_kpi", {"kpi": "revenue", "brand": "Dettol", "period": "YTD"}),
        {"role": "assistant", "content": "Revenue was ₹99.9 L."},
        {"role": "assistant", "content": "Revenue was ₹88.8 L."},
    ])
    r = a.ask("What is Dettol revenue?", "Dettol", "YTD", "yoy")
    assert "₹88.8 L" not in r["answer"] and "₹99.9 L" not in r["answer"]
    assert r["provider"].startswith("offline")


def test_tool_results_go_back_with_the_assistant_message_intact(offline):
    a = Assistant(cfg=Settings("gemini", "fake", ("fake",), "http://x", "k"))
    a.tools, a.offline = offline.tools, offline.offline
    call = _call("get_kpi", {"kpi": "units", "brand": "Veet", "period": "PQ"})
    call["tool_calls"][0]["extra_content"] = {"google": {"thought_signature": "SIG"}}
    a.client = FakeClient([call, {"role": "assistant", "content": "Done."}])
    a.ask("Veet units last quarter?", "Veet")
    second = a.client.seen[1]
    assert second[-2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG"  # Gemini needs it back
    assert second[-1]["role"] == "tool" and json.loads(second[-1]["content"])["brand"] == "Veet"
