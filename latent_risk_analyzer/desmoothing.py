"""
desmoothing.py
==============

Geltner first-order de-smoothing.

WHY DE-SMOOTH?
--------------
Appraisal-based / private-market returns (real estate, private equity, private
credit) are reported infrequently and rely on stale or smoothed valuations.
Reported returns therefore behave like a moving average of the *true* economic
returns: they show artificially LOW volatility and HIGH positive
autocorrelation. This understates risk and overstates risk-adjusted return.

THE MODEL (Geltner, 1991/1993)
------------------------------
Geltner models the reported return as a weighted average of the current true
return and the previous reported return:

    r_reported_t = (1 - rho) * r_true_t + rho * r_reported_{t-1}

where ``rho`` is the smoothing parameter, estimated by the lag-1
autocorrelation of the reported series. Solving for the true (unsmoothed)
return gives the de-smoothing formula:

    r_true_t = (r_reported_t - rho * r_reported_{t-1}) / (1 - rho)

Key properties:
  * the long-run MEAN is (approximately) preserved,
  * VOLATILITY increases (the hidden risk is revealed),
  * autocorrelation is largely removed.

FIRST OBSERVATION
-----------------
The formula needs ``r_reported_{t-1}``, which does not exist for the first
period. We therefore leave the first de-smoothed observation equal to the
first reported observation (an unbiased, defensible choice that avoids
fabricating a pre-sample value). This is documented and configurable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DesmoothResult:
    data: pd.DataFrame          # adds 'desmoothed_return' to the input frame
    rho_estimated: float        # raw lag-1 autocorrelation
    rho_used: float             # rho after safeguards / override
    rho_source: str             # 'estimated' | 'override' | 'capped' | 'floored'
    warnings: list[str]


def estimate_rho(returns: pd.Series) -> float:
    """
    Estimate the lag-1 autocorrelation (the Geltner smoothing parameter).

    Uses Pearson correlation between r_t and r_{t-1}. Returns 0.0 if it cannot
    be computed (e.g. constant series, < 3 observations).
    """
    r = pd.to_numeric(pd.Series(returns), errors="coerce").dropna().to_numpy()
    if len(r) < 3:
        return 0.0
    r0, r1 = r[1:], r[:-1]
    if np.std(r0) == 0 or np.std(r1) == 0:
        return 0.0
    rho = float(np.corrcoef(r0, r1)[0, 1])
    if np.isnan(rho):
        return 0.0
    return rho


def _apply_safeguards(
    rho_est: float,
    rho_override: float | None,
    rho_max: float,
    n_obs: int,
) -> tuple[float, str, list[str]]:
    """
    Apply robustness safeguards to the smoothing parameter.

    Guards against:
      * a user override,
      * rho >= rho_max (de-smoothing blows up as rho -> 1),
      * negative rho (reported series shows mean reversion, not smoothing --
        de-smoothing is not appropriate, so we floor at 0),
      * too few observations to trust the estimate.
    """
    warnings: list[str] = []

    if rho_override is not None:
        rho = float(rho_override)
        if rho >= rho_max:
            rho = rho_max
            warnings.append(
                f"Override rho capped at rho_max={rho_max:.2f} for stability."
            )
        if rho < 0:
            warnings.append("Override rho is negative; de-smoothing will be muted.")
        return rho, "override", warnings

    if n_obs < 12:
        warnings.append(
            f"Only {n_obs} observations: the autocorrelation estimate is "
            "statistically unreliable. Consider overriding rho manually."
        )

    rho = rho_est
    if rho < 0:
        warnings.append(
            f"Estimated rho={rho_est:.3f} is negative (mean reversion, not "
            "smoothing). Floored to 0.0 -> de-smoothed = reported."
        )
        return 0.0, "floored", warnings

    if rho >= rho_max:
        warnings.append(
            f"Estimated rho={rho_est:.3f} is too close to 1; the de-smoothing "
            f"denominator (1-rho) explodes. Capped to rho_max={rho_max:.2f}."
        )
        return rho_max, "capped", warnings

    return rho, "estimated", warnings


def desmooth(
    data: pd.DataFrame,
    return_col: str = "reported_return",
    rho_override: float | None = None,
    rho_max: float = 0.95,
) -> DesmoothResult:
    """
    Add a 'desmoothed_return' column to ``data`` using Geltner de-smoothing.

    Parameters
    ----------
    data : DataFrame with a date column and ``return_col``.
    return_col : name of the reported-return column.
    rho_override : if provided, use this rho instead of the estimate.
    rho_max : safeguard cap on rho.

    Returns
    -------
    DesmoothResult
    """
    df = data.copy().reset_index(drop=True)
    reported = pd.to_numeric(df[return_col], errors="coerce")

    rho_est = estimate_rho(reported)
    rho, source, warnings = _apply_safeguards(
        rho_est, rho_override, rho_max, n_obs=len(reported)
    )

    # Geltner de-smoothing:  u_t = (r_t - rho * r_{t-1}) / (1 - rho)
    denom = 1.0 - rho
    if abs(denom) < 1e-9:
        denom = 1e-9  # final guard (should be unreachable after the cap)

    lagged = reported.shift(1)
    unsmoothed = (reported - rho * lagged) / denom

    # First observation has no lag -> keep it equal to the reported value.
    unsmoothed.iloc[0] = reported.iloc[0]

    df["desmoothed_return"] = unsmoothed.values
    return DesmoothResult(
        data=df,
        rho_estimated=rho_est,
        rho_used=rho,
        rho_source=source,
        warnings=warnings,
    )
