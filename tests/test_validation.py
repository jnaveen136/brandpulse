from pipeline.validate import run_checks, summarize


def test_workbook_passes_validation(tables):
    results = run_checks(tables)
    assert summarize(results)["errors"] == 0


def test_validation_catches_bad_revenue(tables):
    broken = {k: v.copy() for k, v in tables.items()}
    broken["Fact_Sales"].loc[0, "Revenue"] = -5
    failed = {r.check for r in run_checks(broken) if not r.passed and r.severity == "error"}
    assert {"revenue_positive", "revenue_equals_units_x_price"} <= failed


def test_validation_catches_orphan_product(tables):
    broken = {k: v.copy() for k, v in tables.items()}
    broken["Fact_Sales"].loc[0, "ProductID"] = "SKU9999"
    failed = [r for r in run_checks(broken) if r.check == "foreign_key" and not r.passed]
    assert failed and failed[0].failing_rows == 1


def test_known_gaps_are_reported(tables):
    warn = {r.check for r in run_checks(tables) if r.severity == "warning" and not r.passed}
    assert {"market_share_coverage", "marketing_has_no_brand", "calendar_complete"} <= warn
