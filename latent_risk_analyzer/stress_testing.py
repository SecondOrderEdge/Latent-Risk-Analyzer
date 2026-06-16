"""
stress_testing.py
=================

Sensitivity-based stress testing for private-market return streams.

PHILOSOPHY  (read this!)
------------------------
Private-market returns have no reliable observable market beta. Rather than
pretend we can forecast a precise outcome, this engine translates a macro
*scenario* (a bundle of factor shocks) into an estimated return impact using
USER-EDITABLE sensitivities (betas). The output is a SENSITIVITY-BASED
ESTIMATE, not a forecast. Change the betas and you change the answer -- that is
the point: it makes the analyst's assumptions explicit and stress-able.

THE LINEAR FACTOR MAP
---------------------
For a scenario with shocks (equity, credit_spread, rates, inflation,
liquidity, cap_rate, nav_markdown) and sensitivities from the assumptions:

    impact = stress_multiplier * (
          equity_beta        * equity
        + credit_beta        * (credit_spread / 100)     # per +100bps
        - duration           * (rates / 10000)           # price = -D * dRate
        + inflation_beta     * inflation                  # per +1pp
        + liquidity_beta     * liquidity                  # at intensity 1.0
        + caprate_beta       * (cap_rate / 100)           # per +100bps
        + nav_markdown_beta  * nav_markdown
    )

See config.py for the full unit/sign conventions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# Factor keys recognised inside a scenario definition.
FACTORS = [
    "equity",
    "credit_spread",
    "rates",
    "inflation",
    "liquidity",
    "cap_rate",
    "nav_markdown",
]


def scenario_impact(scenario: dict, assumptions: dict) -> tuple[float, dict]:
    """
    Map one scenario's shocks to an estimated return impact.

    Returns (total_impact, contributions_by_factor).
    """
    sm = assumptions.get("stress_multiplier", 1.0)

    eq = scenario.get("equity", 0.0)
    cs = scenario.get("credit_spread", 0.0)
    rt = scenario.get("rates", 0.0)
    inf = scenario.get("inflation", 0.0)
    liq = scenario.get("liquidity", 0.0)
    cap = scenario.get("cap_rate", 0.0)
    nav = scenario.get("nav_markdown", 0.0)

    contrib = {
        "equity": assumptions["equity_beta"] * eq,
        "credit_spread": assumptions["credit_beta"] * (cs / 100.0),
        "rates": -assumptions["duration"] * (rt / 10000.0),
        "inflation": assumptions["inflation_beta"] * inf,
        "liquidity": assumptions["liquidity_beta"] * liq,
        "cap_rate": assumptions["caprate_beta"] * (cap / 100.0),
        "nav_markdown": assumptions["nav_markdown_beta"] * nav,
    }
    total = sm * sum(contrib.values())
    # Scale the reported contributions by the multiplier too (for transparency).
    contrib = {k: sm * v for k, v in contrib.items()}
    return float(total), contrib


def _recovery_periods(drawdown: float, recovery_return: float) -> float:
    """
    Estimate periods to recover a drawdown given an expected per-period return.

    Solves (1 + drawdown) * (1 + g)^t = 1  ->  t = -ln(1+dd) / ln(1+g).
    Returns NaN when recovery is impossible (g <= 0 with a loss, or a total
    wipeout where 1 + drawdown <= 0).
    """
    if drawdown >= 0:
        return 0.0
    if drawdown <= -0.9999:
        return float("inf")  # ~total loss: never recovers at any finite rate
    if recovery_return is None or recovery_return <= 0:
        return float("nan")
    return float(-np.log1p(drawdown) / np.log1p(recovery_return))


def _downside_percentile(impact: float, mean: float, sigma: float) -> float:
    """
    Where does this impact sit in the (normal) de-smoothed return distribution?

    Returns a percentile in [0, 100]. A small number means a severe tail event.
    """
    if sigma is None or sigma <= 0 or np.isnan(sigma):
        return float("nan")
    return float(scipy_stats.norm.cdf(impact, loc=mean, scale=sigma) * 100.0)


def run_scenario(
    name: str,
    scenario: dict,
    assumptions: dict,
    reported_vol_annual: float,
    desmoothed_vol_annual: float,
    desmoothed_mean_annual: float,
    periods_per_year: int,
) -> dict:
    """
    Evaluate a single scenario and return a results row.

    A scenario is treated as a crisis-horizon (roughly one-year) shock, so it is
    compared against ANNUALIZED volatility -- the standard headline risk number.
    The large standard-deviation counts that severe scenarios produce against a
    smoothed series are themselves the point: they show how far outside
    "normal" experience a stress event sits.
    """
    impact, contrib = scenario_impact(scenario, assumptions)

    # The scenario shock is treated as the trough impact -> estimated drawdown.
    estimated_drawdown = min(impact, 0.0)

    # Stressed return = expected (annualized) de-smoothed return + scenario impact.
    stressed_return = desmoothed_mean_annual + impact

    # Impact expressed in standard deviations of each (annualized) vol regime.
    impact_vs_reported_vol = (
        impact / reported_vol_annual if reported_vol_annual else float("nan")
    )
    impact_vs_desmoothed_vol = (
        impact / desmoothed_vol_annual if desmoothed_vol_annual else float("nan")
    )

    # Downside percentile under a normal de-smoothed (annualized) distribution.
    downside_pct = _downside_percentile(
        impact, desmoothed_mean_annual, desmoothed_vol_annual
    )

    # Recovery uses a user-supplied per-period return, else the de-smoothed
    # mean converted from annual to per-period.
    rec_ret = assumptions.get("recovery_return_per_period")
    if rec_ret is None:
        rec_ret = (1.0 + desmoothed_mean_annual) ** (1.0 / periods_per_year) - 1.0
    rec_periods = _recovery_periods(estimated_drawdown, rec_ret)
    rec_years = (
        rec_periods / periods_per_year if np.isfinite(rec_periods) else rec_periods
    )

    row = {
        "Scenario": name,
        "Description": scenario.get("description", ""),
        "Stressed return (est.)": stressed_return,
        "Scenario impact": impact,
        "Estimated drawdown": estimated_drawdown,
        "Impact / reported vol (sd)": impact_vs_reported_vol,
        "Impact / de-smoothed vol (sd)": impact_vs_desmoothed_vol,
        "Downside percentile": downside_pct,
        "Recovery (periods)": rec_periods,
        "Recovery (years)": rec_years,
    }
    # Stash factor-level contributions for optional drill-down.
    for f in FACTORS:
        row[f"contrib_{f}"] = contrib.get(f, 0.0)
    return row


def run_stress_tests(
    scenarios: dict,
    assumptions: dict,
    reported_vol_annual: float,
    desmoothed_vol_annual: float,
    desmoothed_mean_annual: float,
    periods_per_year: int,
) -> pd.DataFrame:
    """
    Run every scenario in ``scenarios`` and return a results DataFrame
    (one row per scenario), sorted by estimated drawdown (worst first).

    Volatilities and the de-smoothed mean are ANNUALIZED.
    """
    rows = [
        run_scenario(
            name,
            scen,
            assumptions,
            reported_vol_annual,
            desmoothed_vol_annual,
            desmoothed_mean_annual,
            periods_per_year,
        )
        for name, scen in scenarios.items()
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Estimated drawdown").reset_index(drop=True)
    return df
