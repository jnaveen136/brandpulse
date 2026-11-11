PY ?= python

.PHONY: install data test notebook api web streamlit

install:
	$(PY) -m pip install -r requirements.txt

## Load the Excel workbook, validate it, and write processed Parquet tables + data-quality report
data:
	$(PY) -m pipeline.build_model

test:
	$(PY) -m pytest -q

## Re-run the Phase 1 EDA notebook end to end
notebook:
	$(PY) -m jupyter nbconvert --to notebook --execute --inplace notebooks/phase1_eda.ipynb

## REST API on http://localhost:8000 (docs at /docs)
api:
	$(PY) -m uvicorn api.main:app --reload --port 8000
