"""
data_import.py
==============

Read and clean an Excel return stream.

Expected input layout (header row optional -- it is auto-detected):

    Column A : Date
    Column B : Reported return (decimal e.g. 0.012  OR  percent e.g. 1.2)

The loader:
  * auto-detects the data range (no need to tell it how many rows),
  * drops blank rows and rows with unparseable dates/returns,
  * auto-detects whether returns are in percent or decimal form,
  * sorts ascending by date,
  * detects the return frequency (monthly / quarterly / annual / irregular).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ImportResult:
    """Container for a cleaned return stream and the diagnostics behind it."""

    data: pd.DataFrame                      # columns: date, reported_return
    frequency: str                          # monthly|quarterly|annual|...|irregular
    periods_per_year: int                   # annualization factor
    detected_as_percent: bool               # True if values were /100'd
    n_observations: int
    median_days_between: float
    messages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Frequency detection
# ---------------------------------------------------------------------------
_FREQ_TABLE = [
    # (label, periods_per_year, typical_days, tolerance_days)
    ("daily", 252, 1, 2),
    ("weekly", 52, 7, 3),
    ("monthly", 12, 30, 8),
    ("quarterly", 4, 91, 20),
    ("annual", 1, 365, 60),
]


def detect_frequency(dates: pd.Series) -> tuple[str, int, float]:
    """
    Infer the sampling frequency from the median spacing between dates.

    Returns (label, periods_per_year, median_days_between).
    Falls back to ('irregular', 12, median_days) if spacing is inconsistent.
    """
    dates = pd.to_datetime(pd.Series(dates)).sort_values()
    if len(dates) < 2:
        return "irregular", 12, float("nan")

    diffs = dates.diff().dropna().dt.days
    median_days = float(diffs.median())

    # Consistency check: are most gaps close to the median?
    if median_days > 0:
        rel_spread = (diffs.std() / median_days) if len(diffs) > 1 else 0.0
    else:
        rel_spread = np.inf

    for label, ppy, typical, tol in _FREQ_TABLE:
        if abs(median_days - typical) <= tol:
            # If spacing is wildly inconsistent, flag as irregular but keep the
            # best-guess annualization factor for downstream stats.
            if rel_spread > 0.5:
                return "irregular", ppy, median_days
            return label, ppy, median_days

    return "irregular", 12, median_days


# ---------------------------------------------------------------------------
# Percent vs decimal detection
# ---------------------------------------------------------------------------
def detect_percent_scale(returns: pd.Series) -> bool:
    """
    Heuristic: decide whether the return column is expressed in PERCENT.

    Periodic asset returns are almost always well under 1.0 in decimal form
    (e.g. 0.02 = 2%). If the typical magnitude is large (median |r| > 1 or the
    std is > 1.5) the numbers are very likely percentages (e.g. 2.0 = 2%).
    """
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if r.empty:
        return False
    median_abs = float(r.abs().median())
    # Primary signal: a typical periodic move above ~0.5 in magnitude is
    # implausible as a decimal return (that would be >50% every period) but is
    # entirely ordinary as a percentage (e.g. 1.5 = 1.5%).
    if median_abs > 0.5:
        return True
    # Secondary signals: large tail values or very dispersed data.
    if float(r.abs().quantile(0.90)) > 1.0:
        return True
    if r.std() > 1.0:
        return True
    return False


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------
def _find_two_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """Pick the date column and the first numeric return column from raw cells."""
    if raw.shape[1] < 2:
        raise ValueError(
            "Input must have at least two columns (Date in A, Return in B)."
        )
    # Use the first two columns by position (matches the documented A/B layout).
    out = raw.iloc[:, :2].copy()
    out.columns = ["date", "reported_return"]
    return out


def load_returns(
    source,
    sheet_name=0,
    force_percent: bool | None = None,
    declared_frequency: str | None = None,
) -> ImportResult:
    """
    Load and clean a return stream from an .xlsx file (or any pandas-readable
    Excel source / file-like object).

    Parameters
    ----------
    source : str | path | file-like
        Path to the .xlsx file or an open binary buffer (e.g. Streamlit upload).
    sheet_name : str | int
        Worksheet to read (default: first sheet).
    force_percent : bool | None
        Override percent auto-detection. None = auto-detect.
    declared_frequency : str | None
        Override frequency auto-detection (e.g. "monthly").

    Returns
    -------
    ImportResult
    """
    messages: list[str] = []

    # header=None so we can tolerate files with or without a header row.
    raw = pd.read_excel(source, sheet_name=sheet_name, header=None)
    df = _find_two_columns(raw)

    # Drop a header row if the first row's "return" cell is not numeric.
    first_ret = pd.to_numeric(pd.Series([df.iloc[0, 1]]), errors="coerce").iloc[0]
    if pd.isna(first_ret):
        messages.append(f"Detected & skipped a header row: {tuple(df.iloc[0])}.")
        df = df.iloc[1:].reset_index(drop=True)

    # Parse types.
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["reported_return"] = pd.to_numeric(df["reported_return"], errors="coerce")

    # Drop blank / invalid rows (need BOTH a valid date and a valid return).
    before = len(df)
    df = df.dropna(subset=["date", "reported_return"]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        messages.append(f"Removed {dropped} blank/invalid row(s).")

    if df.empty:
        raise ValueError("No valid (date, return) rows were found in the input.")

    # Sort ascending and de-duplicate dates (keep last).
    df = df.sort_values("date").reset_index(drop=True)
    dup = df["date"].duplicated().sum()
    if dup:
        df = df.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
        messages.append(f"Removed {dup} duplicate date(s) (kept last).")

    # Percent vs decimal.
    if force_percent is None:
        is_percent = detect_percent_scale(df["reported_return"])
    else:
        is_percent = force_percent
    if is_percent:
        df["reported_return"] = df["reported_return"] / 100.0
        messages.append("Returns detected as PERCENT -> divided by 100 to decimals.")
    else:
        messages.append("Returns treated as DECIMAL (no scaling applied).")

    # Frequency.
    if declared_frequency:
        from .config import ANNUALIZATION_FACTORS

        freq = declared_frequency.lower()
        ppy = ANNUALIZATION_FACTORS.get(freq, 12)
        _, _, median_days = detect_frequency(df["date"])
        messages.append(f"Frequency set by user: {freq} ({ppy}/yr).")
    else:
        freq, ppy, median_days = detect_frequency(df["date"])
        messages.append(
            f"Detected frequency: {freq} ({ppy}/yr; "
            f"median {median_days:.0f} days between observations)."
        )

    return ImportResult(
        data=df[["date", "reported_return"]],
        frequency=freq,
        periods_per_year=ppy,
        detected_as_percent=is_percent,
        n_observations=len(df),
        median_days_between=median_days,
        messages=messages,
    )
