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
make test        # 100 tests: KPIs recomputed by hand from the raw Excel
make notebook    # re-run the Phase 1 EDA notebook
```

## Dashboard

```bash
make build   # build the React app once
make api     # serves API + dashboard on http://localhost:8000
# or, while developing the UI:  make api  (one terminal)  +  make web  (another) → http://localhost:5173
```

Pick one of the 5 Reckitt brands; every page then shows only that brand and its real competitors:

| Page | What it answers |
|---|---|
| Overview | KPI cards vs comparison, revenue trend vs same period last year, Health Score breakdown, revenue by sub-category / category / retailer / region / channel |
| Variants & Competitors | each variant vs every same-sub-category SKU in 3 colours (same brand, other Reckitt, external), closest external rival, variant × rival matrix |
| Competitor Intelligence | price gap, discount gap, competitor discount, market share gap, activity index; *who is discounting / gained share / launched* |
| Retailer Performance | revenue, margin, price index, promo response, growth and top SKUs per retailer |
| Marketing & Promotions | promo lift and cost for the brand; company-wide campaign spend and ROI (labelled) |
| Diagnostics | exact volume / mix / price bridge, evidence-checked causes, where the change happened |
| Ask the Data | questions answered from the KPI engine (Phase 6) |

The view (brand, period, comparison, filters) is kept in the URL, so any view can be bookmarked or shared.

## API

```bash
make api   # http://localhost:8000/docs
```

| Endpoint | Page |
|---|---|
| `GET /api/meta` | brands, presets, filter options, KPI catalog, data caveats |
| `GET /api/brands/{brand}/overview` | KPI cards, trend vs comparison, breakdowns, Health Score |
| `GET /api/brands/{brand}/variants` | every variant vs its 3-tier rivals, closest rivals, variant × rival matrix |
| `GET /api/brands/{brand}/competitors` | price gap, discount gap, market share gap, activity, answers |
| `GET /api/brands/{brand}/retailers` | retailer table, top SKUs, price index, promo response, answers |
| `GET /api/brands/{brand}/marketing` | brand promotions + company-wide campaigns |
| `GET /api/brands/{brand}/diagnostics` | why revenue moved |
| `GET /api/kpi/{kpi}` | any KPI as a value, breakdown (`by=`) or series (`grain=`) |

All take `period` (or `start`+`end`), `mode` (`yoy`/`previous`/`none`), `as_of`, and comma-separated `retailers`, `channels`, `tiers`, `regions`.

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
| 3 | FastAPI (page endpoints + generic KPI endpoint, global filters) | ✅ |
| 4 | React dashboard (7 pages, brand-centric, every chart reacts to brand/period/filters) | ✅ |
| 5 | Streamlit workbench | ⏳ |
| 6 | Grounded LLM Q&A (Gemini / Ollama) + evaluation | ⏳ |
| 7 | Docs, screenshots | ⏳ |

See [docs/DECISIONS.md](docs/DECISIONS.md) for every definition and data caveat.
