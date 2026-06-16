"""
charts.py
=========

Matplotlib chart builders. Each function returns a matplotlib Figure so the
caller can either embed it (Streamlit) or save it to PNG via ``save_all_charts``.

Charts:
  * reported vs de-smoothed return series
  * cumulative growth of $1 (reported vs de-smoothed)
  * drawdown chart
  * rolling volatility chart
  * stress-test scenario bar chart
  * distribution comparison histogram
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")  # headless / server-safe backend
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .stats import cumulative_growth, drawdown_series  # noqa: E402

_REP = "#1f77b4"   # reported (blue)
_DES = "#d62728"   # de-smoothed (red)


def _finish(fig, ax, title, xlabel=None, ylabel=None):
    ax.set_title(title, fontsize=12, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def return_series_chart(data: pd.DataFrame):
    """Reported vs de-smoothed periodic returns over time."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(data["date"], data["reported_return"], label="Reported",
            color=_REP, linewidth=1.4)
    ax.plot(data["date"], data["desmoothed_return"], label="De-smoothed",
            color=_DES, linewidth=1.0, alpha=0.85)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.legend()
    return _finish(fig, ax, "Reported vs De-smoothed Returns", "Date", "Periodic return")


def cumulative_growth_chart(data: pd.DataFrame):
    """Growth of $1 for reported vs de-smoothed."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(data["date"], cumulative_growth(data["reported_return"]),
            label="Reported", color=_REP, linewidth=1.6)
    ax.plot(data["date"], cumulative_growth(data["desmoothed_return"]),
            label="De-smoothed", color=_DES, linewidth=1.6)
    ax.legend()
    return _finish(fig, ax, "Cumulative Growth of $1", "Date", "Value of $1")


def drawdown_chart(data: pd.DataFrame):
    """Underwater (drawdown) chart for reported vs de-smoothed."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    dd_rep = drawdown_series(data["reported_return"])
    dd_des = drawdown_series(data["desmoothed_return"])
    ax.fill_between(data["date"], dd_rep, 0, color=_REP, alpha=0.25, label="Reported")
    ax.fill_between(data["date"], dd_des, 0, color=_DES, alpha=0.25, label="De-smoothed")
    ax.plot(data["date"], dd_rep, color=_REP, linewidth=1.0)
    ax.plot(data["date"], dd_des, color=_DES, linewidth=1.0)
    ax.legend()
    return _finish(fig, ax, "Drawdown (Underwater) Chart", "Date", "Drawdown")


def rolling_volatility_chart(data: pd.DataFrame, periods_per_year: int, window: int | None = None):
    """Annualized rolling volatility for reported vs de-smoothed."""
    if window is None:
        # ~1 year window, but never larger than half the sample.
        window = max(3, min(periods_per_year, len(data) // 2))
    fig, ax = plt.subplots(figsize=(10, 4.5))
    scale = np.sqrt(periods_per_year)
    roll_rep = data["reported_return"].rolling(window).std(ddof=1) * scale
    roll_des = data["desmoothed_return"].rolling(window).std(ddof=1) * scale
    ax.plot(data["date"], roll_rep, label="Reported", color=_REP, linewidth=1.4)
    ax.plot(data["date"], roll_des, label="De-smoothed", color=_DES, linewidth=1.4)
    ax.legend()
    return _finish(
        fig, ax,
        f"Rolling Annualized Volatility ({window}-period window)",
        "Date", "Annualized volatility",
    )


def stress_bar_chart(stress_df: pd.DataFrame, value_col: str = "Estimated drawdown"):
    """Horizontal bar chart of a stress-test metric across scenarios."""
    df = stress_df.sort_values(value_col)
    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.45 * len(df) + 1)))
    colors = [_DES if v < 0 else "#2ca02c" for v in df[value_col]]
    ax.barh(df["Scenario"], df[value_col], color=colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.7)
    ax.set_xlabel(value_col)
    return _finish(fig, ax, f"Stress Test: {value_col}")


def distribution_histogram(data: pd.DataFrame, bins: int = 30):
    """Overlaid histograms of reported vs de-smoothed period returns."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.hist(data["reported_return"].dropna(), bins=bins, color=_REP, alpha=0.5,
            label="Reported", density=True)
    ax.hist(data["desmoothed_return"].dropna(), bins=bins, color=_DES, alpha=0.5,
            label="De-smoothed", density=True)
    ax.legend()
    return _finish(fig, ax, "Return Distribution: Reported vs De-smoothed",
                   "Periodic return", "Density")


def build_all_charts(data: pd.DataFrame, stress_df: pd.DataFrame, periods_per_year: int) -> dict:
    """Return a dict {name: Figure} of every chart."""
    charts = {
        "return_series": return_series_chart(data),
        "cumulative_growth": cumulative_growth_chart(data),
        "drawdown": drawdown_chart(data),
        "rolling_volatility": rolling_volatility_chart(data, periods_per_year),
        "distribution": distribution_histogram(data),
    }
    if stress_df is not None and not stress_df.empty:
        charts["stress_drawdown"] = stress_bar_chart(stress_df, "Estimated drawdown")
        charts["stress_impact"] = stress_bar_chart(stress_df, "Scenario impact")
    return charts


def save_all_charts(charts: dict, out_dir: str) -> list[str]:
    """Save every figure in ``charts`` to ``out_dir`` as PNG. Returns paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, fig in charts.items():
        path = os.path.join(out_dir, f"{name}.png")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        paths.append(path)
    return paths
