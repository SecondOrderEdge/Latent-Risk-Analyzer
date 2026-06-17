"""Tests for the sensitivity-based stress engine."""

from __future__ import annotations

import numpy as np

from latent_risk_analyzer import config, stress_testing


def test_scenario_impact_known_calculation():
    a = {
        "equity_beta": 0.5, "credit_beta": -0.02, "duration": 2.0,
        "inflation_beta": -0.01, "liquidity_beta": -0.10, "caprate_beta": -0.05,
        "nav_markdown_beta": 0.5, "stress_multiplier": 1.0,
    }
    scen = {
        "equity": -0.4, "credit_spread": 200, "rates": 100, "inflation": 3,
        "liquidity": 0.5, "cap_rate": 100, "nav_markdown": -0.1,
    }
    total, contrib = stress_testing.scenario_impact(scen, a)
    # -0.2 -0.04 -0.02 -0.03 -0.05 -0.05 -0.05
    assert abs(total - (-0.44)) < 1e-9
    assert abs(contrib["equity"] - (-0.2)) < 1e-9


def test_stress_multiplier_scales_impact():
    a = config.default_assumptions()
    scen = {"equity": -0.3}
    base, _ = stress_testing.scenario_impact(scen, {**a, "stress_multiplier": 1.0})
    doubled, _ = stress_testing.scenario_impact(scen, {**a, "stress_multiplier": 2.0})
    assert abs(doubled - 2 * base) < 1e-12


def test_recovery_periods_total_loss_is_infinite():
    assert stress_testing._recovery_periods(-1.0, 0.02) == float("inf")


def test_recovery_periods_no_growth_is_nan():
    assert np.isnan(stress_testing._recovery_periods(-0.2, 0.0))


def test_recovery_periods_basic():
    # 20% drawdown, 10% per-period growth -> ln(1/0.8)/ln(1.1).
    t = stress_testing._recovery_periods(-0.2, 0.10)
    assert abs(t - (-np.log(0.8) / np.log(1.1))) < 1e-9


def test_run_stress_tests_structure():
    scenarios = config.all_scenarios()
    a = config.default_assumptions()
    df = stress_testing.run_stress_tests(
        scenarios, a, reported_vol_annual=0.05,
        desmoothed_vol_annual=0.08, desmoothed_mean_annual=0.06,
        periods_per_year=4,
    )
    assert len(df) == len(scenarios)
    for col in ["Scenario", "Scenario impact", "Estimated drawdown",
                "Downside percentile", "Recovery (years)"]:
        assert col in df.columns
    # Sorted worst (most negative drawdown) first.
    assert df["Estimated drawdown"].is_monotonic_increasing


def test_downside_percentile_bounds():
    p = stress_testing._downside_percentile(-0.5, 0.06, 0.08)
    assert 0.0 <= p <= 100.0
