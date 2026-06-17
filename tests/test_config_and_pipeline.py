"""Tests for config presets, the pipeline, and exports."""

from __future__ import annotations

import openpyxl
import pytest

from latent_risk_analyzer import (
    config,
    excel_export,
    pdf_report,
    pipeline,
)


# --- presets ---------------------------------------------------------------
def test_preset_betas_has_all_keys():
    for name in config.ASSET_CLASS_PRESETS:
        betas = config.preset_betas(name)
        assert set(betas) == set(config.BETA_KEYS)


def test_apply_preset_changes_betas():
    a = config.default_assumptions()
    config.apply_preset(a, "Venture / growth equity")
    assert a["equity_beta"] == 0.80
    assert a["nav_markdown_beta"] == 0.70


def test_unknown_preset_raises():
    with pytest.raises(KeyError):
        config.preset_betas("Nonexistent")


def test_real_estate_hedges_inflation():
    a = config.default_assumptions()
    config.apply_preset(a, "Core real estate")
    assert a["inflation_beta"] > 0  # real estate is a partial inflation hedge


# --- pipeline --------------------------------------------------------------
def test_run_analysis_end_to_end(xlsx_file):
    res = pipeline.run_analysis(xlsx_file)
    assert "desmoothed_return" in res.data.columns
    assert res.periods_per_year == 4
    assert not res.stress_df.empty
    assert {"Metric", "Reported", "De-smoothed"} <= set(res.summary_table.columns)


def test_run_analysis_respects_asset_class(xlsx_file):
    a = config.default_assumptions()
    config.apply_preset(a, "Private credit / direct lending")
    res = pipeline.run_analysis(xlsx_file, assumptions=a)
    assert res.assumptions["credit_beta"] == -0.08


# --- exports ---------------------------------------------------------------
def test_excel_export_bytes_and_sheets(xlsx_file):
    res = pipeline.run_analysis(xlsx_file)
    data = excel_export.export_to_bytes(
        data=res.data, summary_table=res.summary_table,
        stress_df=res.stress_df, assumptions=res.assumptions,
        desmooth_meta=pipeline.desmooth_meta(res),
        periods_per_year=res.periods_per_year,
    )
    assert data[:2] == b"PK"  # xlsx is a zip
    import io
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == [
        "Overview", "Returns", "Summary Stats", "Scenarios",
        "Assumptions", "Charts",
    ]


def test_pdf_export_bytes(xlsx_file):
    res = pipeline.run_analysis(xlsx_file)
    data = pdf_report.pdf_to_bytes(
        data=res.data, summary_table=res.summary_table,
        stress_df=res.stress_df, assumptions=res.assumptions,
        desmooth_meta=pipeline.desmooth_meta(res),
        periods_per_year=res.periods_per_year,
    )
    assert data[:4] == b"%PDF"
    assert len(data) > 5000
