"""Tests for Excel/CSV import, cleaning and detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from latent_risk_analyzer import data_import


def test_clean_numeric_handles_messy_strings():
    s = pd.Series(["4.30%", "1,234", "$5.5", "(1.2)", "", "nan"])
    vals, had_pct = data_import.clean_numeric(s)
    assert had_pct is True
    assert vals.iloc[0] == 4.30
    assert vals.iloc[1] == 1234
    assert vals.iloc[2] == 5.5
    assert vals.iloc[3] == -1.2
    assert pd.isna(vals.iloc[4]) and pd.isna(vals.iloc[5])


def test_detect_percent_scale():
    assert data_import.detect_percent_scale(pd.Series([1.5, -0.5, 2.0])) is True
    assert data_import.detect_percent_scale(pd.Series([0.01, 0.02, -0.01])) is False


def test_detect_frequency_quarterly():
    dates = pd.date_range("2010-03-31", periods=12, freq="QE")
    label, ppy, _ = data_import.detect_frequency(dates)
    assert label == "quarterly" and ppy == 4


def test_detect_frequency_monthly():
    dates = pd.date_range("2010-01-31", periods=24, freq="ME")
    label, ppy, _ = data_import.detect_frequency(dates)
    assert label == "monthly" and ppy == 12


def test_load_xlsx_basic(xlsx_file):
    imp = data_import.load_returns(xlsx_file)
    assert imp.n_observations == 80
    assert list(imp.data.columns) == ["date", "reported_return"]
    assert imp.data["date"].is_monotonic_increasing
    assert imp.frequency == "quarterly"


def test_load_csv_vendor_export_picks_net_of_fees(black_diamond_csv):
    imp = data_import.load_returns(black_diamond_csv)
    # Auto-pick should prefer the net-of-fees stream and ignore Linked/Bench.
    assert imp.return_column == "NOF Return"
    assert "GOF Return" in imp.candidate_return_columns
    assert imp.detected_as_percent is True  # '%' signs present
    # First NOF return was -0.50% -> -0.005 decimal.
    assert abs(imp.data["reported_return"].iloc[0] - (-0.005)) < 1e-9


def test_return_column_override(black_diamond_csv):
    imp = data_import.load_returns(black_diamond_csv, return_column="GOF Return")
    assert imp.return_column == "GOF Return"
    assert abs(imp.data["reported_return"].iloc[0] - (-0.004)) < 1e-9


def test_blank_rows_removed_and_sorted(tmp_path):
    dates = pd.date_range("2015-01-31", periods=4, freq="ME")
    df = pd.DataFrame({
        "Date": [dates[2], None, dates[0], dates[1]],
        "Return": [0.01, None, 0.02, np.nan],
    })
    df = pd.concat([df, pd.DataFrame({"Date": [dates[3]], "Return": [0.015]})])
    p = tmp_path / "blank.xlsx"
    df.to_excel(p, index=False)
    imp = data_import.load_returns(str(p))
    assert imp.n_observations == 3
    assert imp.data["date"].is_monotonic_increasing


def test_no_header_positional_fallback(tmp_path):
    dates = pd.date_range("2015-01-31", periods=6, freq="ME")
    df = pd.DataFrame({"a": dates, "b": [0.01, 0.02, 0.0, -0.01, 0.03, 0.02]})
    p = tmp_path / "nohdr.xlsx"
    df.to_excel(p, index=False, header=False)
    imp = data_import.load_returns(str(p))
    assert imp.n_observations == 6


def test_trailing_zero_returns_flagged(tmp_path):
    dates = pd.date_range("2015-01-31", periods=6, freq="ME")
    df = pd.DataFrame({
        "Date": dates,
        "Reported Return": [0.01, 0.02, 0.015, 0.03, 0.0, 0.0],
    })
    p = tmp_path / "tail.xlsx"
    df.to_excel(p, index=False)
    imp = data_import.load_returns(str(p))
    assert any("roll-forward" in m for m in imp.messages)
