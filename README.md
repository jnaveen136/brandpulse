# BrandPulse

Brand intelligence platform that tracks Reckitt's 5 core brands (Dettol, Harpic, Veet, Mortein, Lizol) against their real Unilever and P&G competitors.

Built during a Data Engineer internship at KaarTech on the *Brand Intelligence Accelerator* dataset: 20,440 transactions, 55 SKUs, 11 brands, 3 manufacturers, 2024–2025.

## Architecture

```
Excel workbook
   │
   ▼
pipeline/      L0  ingest + 46 validation checks → reports/data_quality.md
               L1  enriched model → data/processed/*.parquet
   │
   ▼
kpi/           L2  KPI registry + engine + Time Intelligence + Brand Health Score
               L3  competitor mapping + diagnostics            (Phase 2)
   │
   ├──► api/            FastAPI                                  (Phase 3)
   │      ├──► web/            React brand-manager dashboard     (Phase 4)
   │      └──► streamlit_app/  analyst workbench                 (Phase 5)
   └──► llm/            grounded Q&A, Gemini or Ollama           (Phase 6)
```

All numbers in the dashboard, the workbench and the Q&A come from the same `kpi.engine.Engine`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make data        # validate the workbook and build data/processed/
make test        # 61 tests: KPIs recomputed by hand from the raw Excel
make notebook    # re-run the Phase 1 EDA notebook
```

## Using the KPI engine

```python
from kpi.engine import Engine
from kpi.filters import Filters

eng = Engine()
dettol = Filters.make(brands="Dettol")

eng.value("revenue", dettol, period="YTD")                       # one number
eng.compare("asp", dettol, period="MTD", mode="previous")        # vs. same days last month
eng.breakdown("price_index", "Retailer", dettol, period="L13W")  # per retailer
eng.timeseries("revenue", grain="W", filters=dettol, period="R90")
```

**Time Intelligence presets:** `WTD MTD QTD YTD R7 R30 R90 PM PQ L13W PY ALL`, or a `(start, end)` tuple.
**Comparison modes:** `previous` (the period before, same shape) and `yoy` (same period last year).

### Competitors and diagnostics

```python
from kpi.competitive import Competitive
from kpi.diagnostics import Diagnostics

comp = Competitive(eng)
comp.closest_rivals("Dettol")            # external brands ranked by variant overlap
comp.variant_table("Dettol", "YTD")      # each variant vs its 3-tier rivals
comp.price_position("Dettol", "YTD")     # price gap %, discount gap, competitor discount %
comp.answers("Dettol", "YTD")            # who is discounting / gained share / launched

Diagnostics(eng, comp).explain("Harpic", "MTD", "previous")   # why revenue moved
```

The full variant-to-rival mapping is in [reports/competitor_map.csv](reports/competitor_map.csv).

**KPIs:** run `python -c "from kpi.registry import catalog; print(catalog()[['id','name','formula_text']])"` to list them with their formulas.

## Project status

| Phase | Contents | Status |
|---|---|---|
| 0 | Repo, CI, Makefile | ✅ |
| 1 | Validation, data model, KPI engine, Time Intelligence, Health Score, tests, EDA notebook | ✅ |
| 2 | Competitor mapping (3 tiers), competitor KPIs, diagnostics engine | ✅ |
| 3 | FastAPI | ⏳ |
| 4 | React dashboard | ⏳ |
| 5 | Streamlit workbench | ⏳ |
| 6 | Grounded LLM Q&A (Gemini / Ollama) + evaluation | ⏳ |
| 7 | Docs, screenshots | ⏳ |

See [docs/DECISIONS.md](docs/DECISIONS.md) for every definition and data caveat.
