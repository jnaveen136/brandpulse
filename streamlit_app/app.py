"""BrandPulse analyst workbench (Streamlit).

The internal tool behind the dashboard: check the data, explore any KPI across
any brand / dimension / period, review the competitor mapping, read the KPI
definitions, try Health Score weights, and see how the Q&A assistant scores
on its evaluation set. Uses the same KPI engine as the dashboard and the API.

Run:  streamlit run streamlit_app/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from kpi import registry as R  # noqa: E402
from kpi import time_intel as T  # noqa: E402
from kpi.competitive import Competitive  # noqa: E402
from kpi.engine import Engine  # noqa: E402
from kpi.filters import DIMENSIONS, SOURCE_DIMENSIONS, Filters  # noqa: E402
from kpi.health_score import WEIGHTS, health_scores  # noqa: E402
from pipeline.schema import CORE_BRANDS  # noqa: E402

st.set_page_config(page_title="BrandPulse workbench", page_icon="◆", layout="wide")

FOCUS, EXTERNAL, PREV = "#2a78d6", "#eb6834", "#9a9993"


@st.cache_resource
def engine() -> Engine:
    return Engine()


@st.cache_resource
def competitive() -> Competitive:
    return Competitive(engine())


@st.cache_data
def health(period: str, mode: str, weights: tuple) -> pd.DataFrame:
    return health_scores(engine(), period, mode, weights=dict(weights))


def fmt(unit: str, v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return {"currency": f"₹{v:,.0f}", "pct": f"{v:.2f}%", "count": f"{v:,.0f}", "rating": f"{v:.2f} ★",
            "index": f"{v:.1f}", "ratio": f"{v:.2f}×"}.get(unit, f"{v:,.2f}")


e = engine()
m = e.m
st.sidebar.title("◆ BrandPulse")
st.sidebar.caption("Analyst workbench")
page = st.sidebar.radio("Page", ["Data quality", "KPI explorer", "Competitor map", "Health Score lab",
                                 "KPI glossary", "Q&A evaluation"])
st.sidebar.divider()
st.sidebar.caption(f"Data: {e.data_start:%d %b %Y} – {e.data_end:%d %b %Y} · {len(m.sales):,} transactions")

# ------------------------------------------------------------------------------------------------
if page == "Data quality":
    st.title("Data quality")
    p = ROOT / "reports" / "data_quality.json"
    if not p.exists():
        st.error("No report yet. Run `make data`.")
        st.stop()
    dq = json.loads(p.read_text())
    s = dq["summary"]
    c = st.columns(4)
    c[0].metric("Status", s["status"].upper())
    c[1].metric("Checks", s["checks"])
    c[2].metric("Errors", s["errors"])
    c[3].metric("Warnings", s["warnings"])
    df = pd.DataFrame(dq["results"])
    df["result"] = df.apply(lambda r: "info" if r["severity"] == "info" else ("pass" if r["passed"] else r["severity"]), axis=1)
    st.subheader("Caveats the dashboard labels")
    for r in df[df["result"].isin(["warning", "error"])].itertuples():
        (st.error if r.result == "error" else st.warning)(f"**{r.check}** ({r.sheet}): {r.detail}")
    for r in df[df["result"] == "info"].itertuples():
        st.info(f"**{r.check}** ({r.sheet}): {r.detail}")
    st.subheader("All checks")
    show = st.multiselect("Show", ["pass", "warning", "error", "info"], ["pass", "warning", "error", "info"])
    st.dataframe(df[df["result"].isin(show)][["result", "check", "sheet", "failing_rows", "detail"]],
                 use_container_width=True, hide_index=True)

# ------------------------------------------------------------------------------------------------
elif page == "KPI explorer":
    st.title("KPI explorer")
    st.caption("Any registered KPI, for any brands, over any period, split by any dimension. Same numbers as the dashboard.")
    kpis = {f"{k.name} ({k.group})": k for k in R.KPIS}
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    k = kpis[c1.selectbox("KPI", list(kpis), index=0)]
    brands = c2.multiselect("Brands (empty = all 11)", sorted(m.products["Brand"].unique()), ["Dettol"])
    preset = c3.selectbox("Period", list(T.PRESETS), index=list(T.PRESETS).index("YTD"),
                          format_func=lambda x: T.PRESETS[x])
    mode = c4.selectbox("Compare with", ["yoy", "previous", "none"], format_func=lambda x: T.COMPARE_MODES[x])
    if k.kind == "growth":
        st.info(f"{k.name} is the change in **{R.get(k.base).name}** between the two periods; exploring that KPI.")
        k = R.get(k.base)

    allowed = SOURCE_DIMENSIONS[k.source]
    with st.expander("Filters"):
        fc = st.columns(4)
        opts = {"retailers": sorted(m.retailers["Retailer"]), "channels": sorted(m.retailers["Channel"].unique()),
                "tiers": sorted(m.retailers["Tier"].unique()), "regions": sorted(m.sales["Region"].unique())}
        chosen = {name: fc[i].multiselect(name.title(), o, disabled=name not in allowed) for i, (name, o) in enumerate(opts.items())}
    f = Filters.make(brands=brands or None, **{kk: v for kk, v in chosen.items() if v})
    if k.source == "events":
        f = Filters.make(manufacturers=["Unilever", "P&G"] if not brands else
                         sorted(m.products[m.products["Brand"].isin(brands)]["Manufacturer"].unique()))

    res = e.compare(k.id, f, preset, mode)
    c = st.columns(4)
    c[0].metric(k.name, fmt(k.unit, res["current"]),
                None if res["delta"] is None else (f"{res['delta']:+.2f}pp" if k.unit == "pct" else f"{res['delta_pct']:+.1f}%"),
                delta_color="normal" if k.higher_is_better else "inverse")
    c[1].metric("Comparison", fmt(k.unit, res["previous"]))
    c[2].markdown(f"**Period**  \n{res['period']['start']} → {res['period']['end']}  \n{res['period']['days']} days")
    c[3].markdown("**Compared with**  \n" + (f"{res['comparison']['start']} → {res['comparison']['end']}  \n"
                  f"{res['comparison']['label']}" if res["comparison"] else "—"))
    if res["ignored_filters"]:
        st.warning(f"{k.name} comes from `{k.source}`, which has no {', '.join(res['ignored_filters'])}: those filters were ignored.")
    if k.scope_note:
        st.info(k.scope_note)
    st.caption(f"Formula: `{k.formula_text}` · {k.description}")

    dims = [d for name, d in DIMENSIONS.items() if name in allowed and name not in ("promotions",)] or ["Brand"]
    t1, t2 = st.tabs(["Breakdown", "Time series"])
    with t1:
        default = "Retailer" if len(brands) == 1 and "Retailer" in dims else ("Brand" if "Brand" in dims else dims[0])
        by = st.selectbox("Split by", dims, index=dims.index(default))
        if k.source in ("marketing",):
            st.info("Company-level KPI: no dimensions to split by.")
        else:
            b = e.breakdown_compare(k.id, by, f, preset, mode)
            ch = alt.Chart(b).mark_bar(cornerRadiusEnd=4, color=FOCUS).encode(
                x=alt.X("current:Q", title=k.name), y=alt.Y(f"{by}:N", sort="-x", title=None),
                tooltip=[by, alt.Tooltip("current:Q", format=",.2f"), alt.Tooltip("previous:Q", format=",.2f"),
                         alt.Tooltip("delta_pct:Q", format="+.1f", title="change %")])
            st.altair_chart(ch, use_container_width=True)
            st.dataframe(b, use_container_width=True, hide_index=True)
    with t2:
        cc = st.columns(2)
        grain = cc[0].radio("Grain", ["D", "W", "M", "Q"], index=2, horizontal=True,
                            format_func=lambda g: {"D": "Day", "W": "Week", "M": "Month", "Q": "Quarter"}[g])
        split = cc[1].selectbox("Lines", ["(none)"] + dims)
        ts = e.timeseries(k.id, grain, f, preset, by=None if split == "(none)" else split)
        if ts.empty:
            st.info("No data in this period.")
        else:
            enc = dict(x=alt.X("bucket:T", title=None), y=alt.Y("value:Q", title=k.name),
                       tooltip=["bucket:T", alt.Tooltip("value:Q", format=",.2f")] + ([split] if split != "(none)" else []))
            if split != "(none)":
                enc["color"] = alt.Color(f"{split}:N")
            st.altair_chart(alt.Chart(ts).mark_line(point=True, strokeWidth=2, color=FOCUS).encode(**enc),
                            use_container_width=True)
            st.dataframe(ts, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------------------------------------
elif page == "Competitor map":
    st.title("Competitor map")
    st.caption("Rule: a core variant competes with every other SKU in the same SubCategory. Category is ignored.")
    comp = competitive()
    brand = st.selectbox("Core brand", CORE_BRANDS)
    cr = comp.closest_rivals(brand)
    st.subheader("Closest external rivals")
    st.altair_chart(alt.Chart(cr).mark_bar(cornerRadiusEnd=4, color=EXTERNAL).encode(
        x=alt.X("variants_overlapped:Q", title="variants overlapped", scale=alt.Scale(domain=[0, int(cr["total_variants"].max())])),
        y=alt.Y("RivalBrand:N", sort="-x", title=None),
        tooltip=["RivalBrand", "RivalManufacturer", "variants_overlapped", "shared_subcategory_revenue"]),
        use_container_width=True)
    mp = comp.map[comp.map["CoreBrand"] == brand]
    tiers = st.multiselect("Tiers", ["self", "reckitt", "external"], ["self", "reckitt", "external"])
    st.dataframe(mp[mp["Tier"].isin(tiers)], use_container_width=True, hide_index=True)
    st.download_button("Download full mapping (CSV)", comp.map.to_csv(index=False), "competitor_map.csv", "text/csv")

# ------------------------------------------------------------------------------------------------
elif page == "Health Score lab":
    st.title("Health Score lab")
    st.caption("Change the weights and see how the ranking moves. Components are scored 0–100 against all 11 brands "
               "(position: against brands with the same source, real share or proxy).")
    c = st.columns(5)
    preset = c[0].selectbox("Period", ["YTD", "QTD", "PQ", "L13W", "R90"], format_func=lambda x: T.PRESETS[x])
    w = {}
    for i, (comp_, default) in enumerate(WEIGHTS.items()):
        w[comp_] = c[i + 1].slider(comp_.title(), 0.0, 1.0, default, 0.05)
    tot = sum(w.values()) or 1.0
    w = {kk: v / tot for kk, v in w.items()}
    st.caption("Weights are normalised to sum to 1: " + ", ".join(f"{kk} {v:.0%}" for kk, v in w.items()))
    h = health(preset, "yoy", tuple(sorted(w.items()))).reset_index()
    h["type"] = h["IsCore"].map({True: "Core (Reckitt)", False: "Competitor"})
    st.altair_chart(alt.Chart(h).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("health_score:Q", scale=alt.Scale(domain=[0, 100]), title="Health Score"),
        y=alt.Y("Brand:N", sort="-x", title=None),
        color=alt.Color("type:N", scale=alt.Scale(range=[FOCUS, PREV]), title=None),
        tooltip=["Brand", "health_score", "growth", "margin", "rating", "position", "position_source"]),
        use_container_width=True)
    st.dataframe(h[["rank", "Brand", "type", "health_score", "growth", "margin", "rating", "position", "position_source",
                    "growth_score", "margin_score", "rating_score", "position_score"]],
                 use_container_width=True, hide_index=True)

# ------------------------------------------------------------------------------------------------
elif page == "KPI glossary":
    st.title("KPI glossary")
    cat = R.catalog()
    group = st.multiselect("Group", sorted(cat["group"].unique()))
    if group:
        cat = cat[cat["group"].isin(group)]
    for k in cat.itertuples():
        with st.expander(f"**{k.name}** · {k.group}"):
            st.write(k.description)
            st.code(k.formula_text, language=None)
            st.caption(f"id `{k.id}` · unit {k.unit} · source `{k.source}` · "
                       f"{'higher is better' if k.higher_is_better else 'lower is better'}"
                       + (f" · {k.scope_note}" if k.scope_note else ""))
    st.subheader("Time Intelligence presets")
    rows = []
    for pid, label in T.PRESETS.items():
        p, _ = e.period(pid)
        prv, yoy = e.comparison_period(pid, "previous"), e.comparison_period(pid, "yoy")
        rows.append({"preset": pid, "meaning": label, "range": f"{p.start:%d %b %Y} – {p.end:%d %b %Y}", "days": p.days,
                     "previous period": f"{prv.start:%d %b %Y} – {prv.end:%d %b %Y}",
                     "same period last year": f"{yoy.start:%d %b %Y} – {yoy.end:%d %b %Y}"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------------------------------------
elif page == "Q&A evaluation":
    st.title("Q&A evaluation")
    p = ROOT / "reports" / "llm_eval.json"
    if not p.exists():
        st.info("No evaluation results yet. Run `make eval` after configuring an LLM provider (see .env.example).")
        st.stop()
    ev = json.loads(p.read_text())
    s = ev["summary"]
    c = st.columns(5)
    c[0].metric("Provider", s["provider"])
    c[1].metric("Questions", s["questions"])
    c[2].metric("Answer accuracy", f"{s['accuracy_pct']:.0f}%")
    c[3].metric("Unsupported figures", f"{s['hallucination_rate_pct']:.1f}%")
    c[4].metric("Correct refusals", f"{s['refusal_accuracy_pct']:.0f}%")
    st.caption(f"Run at {s['run_at']}. Accuracy = the expected value appears in the answer within tolerance. "
               "Unsupported figures = numbers in answers that no tool result supports (shown before the verifier removes them).")
    df = pd.DataFrame(ev["results"])
    st.dataframe(df, use_container_width=True, hide_index=True)
