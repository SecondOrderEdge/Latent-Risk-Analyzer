"""
pipeline.py
===========

High-level orchestration that wires the modules together, used by both the
CLI and the Streamlit app so they stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config, data_import, desmoothing, stats, stress_testing


@dataclass
class AnalysisResult:
    data: pd.DataFrame                 # date, reported_return, desmoothed_return
    import_result: data_import.ImportResult
    desmooth_result: desmoothing.DesmoothResult
    summary_table: pd.DataFrame
    stress_df: pd.DataFrame
    assumptions: dict
    periods_per_year: int


def run_analysis(
    source,
    assumptions: dict | None = None,
    scenarios: dict | None = None,
    force_percent: bool | None = None,
    declared_frequency: str | None = None,
) -> AnalysisResult:
    """
    Full pipeline: import -> de-smooth -> stats -> stress test.

    Parameters
    ----------
    source : path or file-like .xlsx input.
    assumptions : user assumptions dict (defaults used if None). Note: the
        annualization_factor is taken from the detected/declared frequency.
    scenarios : scenario dict (defaults to historical + hypothetical if None).
    force_percent / declared_frequency : importer overrides.
    """
    assumptions = dict(config.default_assumptions() if assumptions is None else assumptions)
    if scenarios is None:
        scenarios = config.all_scenarios()

    # 1) Import & clean -------------------------------------------------------
    # Only override frequency detection when the caller *explicitly* asks for it
    # (passing declared_frequency). The default assumption is NOT used here, so
    # auto-detection remains the default behaviour.
    imp = data_import.load_returns(
        source,
        force_percent=force_percent,
        declared_frequency=declared_frequency,
    )
    ppy = imp.periods_per_year
    assumptions["frequency"] = imp.frequency
    assumptions["annualization_factor"] = ppy

    # 2) De-smooth ------------------------------------------------------------
    des = desmoothing.desmooth(
        imp.data,
        rho_override=assumptions.get("rho_override"),
        rho_max=assumptions.get("rho_max", 0.95),
    )
    data = des.data

    # 3) Summary stats --------------------------------------------------------
    summary_table = stats.comparison_table(
        data, ppy, assumptions["risk_free_rate"]
    )

    # 4) Stress tests (compared against ANNUALIZED volatility) ----------------
    rep_vol = stats.annualized_volatility(data["reported_return"], ppy)
    des_vol = stats.annualized_volatility(data["desmoothed_return"], ppy)
    des_mean = stats.annualized_return(data["desmoothed_return"], ppy)
    stress_df = stress_testing.run_stress_tests(
        scenarios,
        assumptions,
        reported_vol_annual=rep_vol,
        desmoothed_vol_annual=des_vol,
        desmoothed_mean_annual=des_mean,
        periods_per_year=ppy,
    )

    return AnalysisResult(
        data=data,
        import_result=imp,
        desmooth_result=des,
        summary_table=summary_table,
        stress_df=stress_df,
        assumptions=assumptions,
        periods_per_year=ppy,
    )


def desmooth_meta(res: AnalysisResult) -> dict:
    """Compact de-smoothing diagnostics dict (for the Excel Assumptions tab)."""
    d = res.desmooth_result
    return {
        "rho_estimated": round(d.rho_estimated, 4),
        "rho_used": round(d.rho_used, 4),
        "rho_source": d.rho_source,
        "frequency": res.import_result.frequency,
        "periods_per_year": res.periods_per_year,
        "n_observations": res.import_result.n_observations,
        "warnings": " | ".join(d.warnings) if d.warnings else "none",
    }
