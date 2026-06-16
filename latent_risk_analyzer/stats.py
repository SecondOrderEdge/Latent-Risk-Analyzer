"""
stats.py
========

Summary statistics for a periodic return series, computed identically for the
reported and the de-smoothed streams so they can be compared side-by-side.

All "annualized" figures use the periods-per-year annualization factor that
the importer detected (or the user declared).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def cumulative_growth(returns: pd.Series) -> pd.Series:
    """Growth of $1: cumulative product of (1 + r)."""
    r = pd.to_numeric(pd.Series(returns), errors="coerce").fillna(0.0)
    return (1.0 + r).cumprod()


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Drawdown path: (cumulative / running peak) - 1, always <= 0."""
    growth = cumulative_growth(returns)
    running_peak = growth.cummax()
    return growth / running_peak - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """Worst peak-to-trough decline (a negative number)."""
    dd = drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def annualized_return(returns: pd.Series, periods_per_year: int) -> float:
    """Geometric (CAGR-style) annualized return."""
    r = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    n = len(r)
    if n == 0:
        return float("nan")
    total_growth = float((1.0 + r).prod())
    if total_growth <= 0:
        return float("nan")  # total loss -> CAGR undefined
    return total_growth ** (periods_per_year / n) - 1.0


def annualized_volatility(returns: pd.Series, periods_per_year: int) -> float:
    """Annualized standard deviation (sample std, ddof=1)."""
    r = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(
    returns: pd.Series, periods_per_year: int, risk_free_rate: float
) -> float:
    """
    Annualized Sharpe ratio = (annualized return - rf) / annualized vol.

    ``risk_free_rate`` is the ANNUAL risk-free rate (decimal).
    """
    ann_ret = annualized_return(returns, periods_per_year)
    ann_vol = annualized_volatility(returns, periods_per_year)
    if ann_vol is None or ann_vol == 0 or np.isnan(ann_vol):
        return float("nan")
    return (ann_ret - risk_free_rate) / ann_vol


def lag1_autocorrelation(returns: pd.Series) -> float:
    """Lag-1 autocorrelation of the series."""
    from .desmoothing import estimate_rho

    return estimate_rho(returns)


def summary(
    returns: pd.Series,
    periods_per_year: int,
    risk_free_rate: float,
) -> dict:
    """Compute the full statistics dict for one return series."""
    r = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    if len(r) == 0:
        return {k: float("nan") for k in _STAT_KEYS}

    return {
        "n_observations": int(len(r)),
        "annualized_return": annualized_return(r, periods_per_year),
        "annualized_volatility": annualized_volatility(r, periods_per_year),
        "sharpe_ratio": sharpe_ratio(r, periods_per_year, risk_free_rate),
        "max_drawdown": max_drawdown(r),
        "best_period": float(r.max()),
        "worst_period": float(r.min()),
        "mean_period_return": float(r.mean()),
        "period_volatility": float(r.std(ddof=1)) if len(r) > 1 else float("nan"),
        "autocorrelation": lag1_autocorrelation(r),
        "skewness": float(scipy_stats.skew(r)),
        "kurtosis_excess": float(scipy_stats.kurtosis(r)),  # excess (normal=0)
    }


_STAT_KEYS = [
    "n_observations",
    "annualized_return",
    "annualized_volatility",
    "sharpe_ratio",
    "max_drawdown",
    "best_period",
    "worst_period",
    "mean_period_return",
    "period_volatility",
    "autocorrelation",
    "skewness",
    "kurtosis_excess",
]


def comparison_table(
    data: pd.DataFrame,
    periods_per_year: int,
    risk_free_rate: float,
    reported_col: str = "reported_return",
    desmoothed_col: str = "desmoothed_return",
) -> pd.DataFrame:
    """
    Build a tidy reported-vs-de-smoothed comparison table (one row per metric).
    """
    rep = summary(data[reported_col], periods_per_year, risk_free_rate)
    des = summary(data[desmoothed_col], periods_per_year, risk_free_rate)

    pretty = {
        "n_observations": "Observations",
        "annualized_return": "Annualized return",
        "annualized_volatility": "Annualized volatility",
        "sharpe_ratio": "Sharpe ratio",
        "max_drawdown": "Max drawdown",
        "best_period": "Best period",
        "worst_period": "Worst period",
        "mean_period_return": "Mean period return",
        "period_volatility": "Period volatility (std)",
        "autocorrelation": "Lag-1 autocorrelation",
        "skewness": "Skewness",
        "kurtosis_excess": "Excess kurtosis",
    }

    rows = []
    for key in _STAT_KEYS:
        rows.append(
            {
                "Metric": pretty[key],
                "Reported": rep[key],
                "De-smoothed": des[key],
            }
        )
    out = pd.DataFrame(rows)

    # Volatility inflation is the headline "hidden risk" number.
    vol_rep = rep["annualized_volatility"]
    vol_des = des["annualized_volatility"]
    inflation = (vol_des / vol_rep - 1.0) if vol_rep else float("nan")
    out.attrs["volatility_inflation"] = inflation
    return out
