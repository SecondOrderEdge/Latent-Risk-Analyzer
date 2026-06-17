"""Tests for the Geltner de-smoothing logic."""

from __future__ import annotations

import numpy as np
import pandas as pd

from latent_risk_analyzer import desmoothing


def test_estimate_rho_recovers_positive_autocorrelation(smoothed_returns):
    rho = desmoothing.estimate_rho(smoothed_returns["reported_return"])
    assert 0.25 < rho < 0.75  # the fixture was built with rho = 0.5


def test_first_observation_unchanged(smoothed_returns):
    res = desmoothing.desmooth(smoothed_returns)
    assert res.data["desmoothed_return"].iloc[0] == \
        smoothed_returns["reported_return"].iloc[0]


def test_desmoothing_inflates_volatility(smoothed_returns):
    res = desmoothing.desmooth(smoothed_returns)
    rep_vol = res.data["reported_return"].std(ddof=1)
    des_vol = res.data["desmoothed_return"].std(ddof=1)
    assert des_vol > rep_vol


def test_mean_approximately_preserved(smoothed_returns):
    res = desmoothing.desmooth(smoothed_returns)
    rep_mean = res.data["reported_return"].mean()
    des_mean = res.data["desmoothed_return"].mean()
    assert abs(des_mean - rep_mean) < 0.01


def test_negative_rho_is_floored():
    # Strongly mean-reverting series -> negative autocorrelation.
    df = pd.DataFrame({
        "date": pd.date_range("2015-01-31", periods=24, freq="ME"),
        "reported_return": [0.02, -0.02] * 12,
    })
    res = desmoothing.desmooth(df)
    assert res.rho_used == 0.0
    assert res.rho_source == "floored"
    # rho = 0 -> de-smoothed identical to reported.
    assert np.allclose(res.data["desmoothed_return"], df["reported_return"])


def test_rho_override_is_capped():
    df = pd.DataFrame({
        "date": pd.date_range("2015-01-31", periods=24, freq="ME"),
        "reported_return": np.linspace(0.01, 0.03, 24),
    })
    res = desmoothing.desmooth(df, rho_override=0.99, rho_max=0.95)
    assert res.rho_used == 0.95
    assert res.rho_source == "override"


def test_formula_matches_manual_calculation():
    # With a fixed rho, check the de-smoothing formula explicitly.
    r = [0.01, 0.02, 0.03, 0.04]
    df = pd.DataFrame({
        "date": pd.date_range("2020-03-31", periods=4, freq="QE"),
        "reported_return": r,
    })
    rho = 0.5
    res = desmoothing.desmooth(df, rho_override=rho)
    expected = [r[0]] + [
        (r[t] - rho * r[t - 1]) / (1 - rho) for t in range(1, 4)
    ]
    assert np.allclose(res.data["desmoothed_return"], expected)


def test_small_sample_warns():
    df = pd.DataFrame({
        "date": pd.date_range("2020-03-31", periods=5, freq="QE"),
        "reported_return": [0.01, 0.02, 0.015, 0.03, 0.01],
    })
    res = desmoothing.desmooth(df)
    assert any("unreliable" in w.lower() for w in res.warnings)
