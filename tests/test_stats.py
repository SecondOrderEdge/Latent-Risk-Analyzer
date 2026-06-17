"""Tests for summary statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from latent_risk_analyzer import stats


def test_annualized_return_geometric():
    r = pd.Series([0.01] * 12)  # constant 1% monthly
    ann = stats.annualized_return(r, periods_per_year=12)
    assert abs(ann - ((1.01 ** 12) - 1)) < 1e-9


def test_annualized_volatility():
    r = pd.Series([0.02, -0.02, 0.02, -0.02, 0.02, -0.02])
    vol = stats.annualized_volatility(r, periods_per_year=12)
    assert abs(vol - r.std(ddof=1) * np.sqrt(12)) < 1e-12


def test_max_drawdown():
    # +10%, -50%, then recovery -> trough drawdown is -50%.
    r = pd.Series([0.10, -0.50, 0.20])
    dd = stats.max_drawdown(r)
    assert abs(dd - (-0.50)) < 1e-9


def test_cumulative_growth():
    r = pd.Series([0.1, 0.1])
    g = stats.cumulative_growth(r)
    assert abs(g.iloc[-1] - 1.21) < 1e-9


def test_sharpe_ratio_sign():
    r = pd.Series([0.02] * 12)
    s = stats.sharpe_ratio(r, periods_per_year=12, risk_free_rate=0.0)
    assert s > 0


def test_summary_has_all_keys():
    r = pd.Series(np.random.default_rng(1).normal(0.01, 0.03, 40))
    out = stats.summary(r, periods_per_year=4, risk_free_rate=0.03)
    for key in stats._STAT_KEYS:
        assert key in out


def test_comparison_table_volatility_inflation():
    data = pd.DataFrame({
        "reported_return": [0.01, 0.011, 0.009, 0.012, 0.01],
        "desmoothed_return": [0.01, 0.03, -0.01, 0.04, 0.0],
    })
    tbl = stats.comparison_table(data, periods_per_year=4, risk_free_rate=0.02)
    assert "volatility_inflation" in tbl.attrs
    # The de-smoothed series is more volatile here.
    assert tbl.attrs["volatility_inflation"] > 0
