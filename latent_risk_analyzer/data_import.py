"""
data_import.py
==============

Read and clean a periodic return stream.

Two input styles are supported automatically:

1. **Simple two-column** files (the documented minimal format):
       Column A : Date
       Column B : Reported return  (decimal 0.012 OR percent 1.2)

2. **Rich vendor exports** (e.g. Black Diamond) with many columns and a header
   row. In this case the loader finds the date column and the return column by
   NAME, so you can drop the raw export in without building a template.

The loader:
  * accepts .xlsx and .csv (and file-like buffers, e.g. Streamlit uploads),
  * auto-detects the data range (no need to state how many rows),
  * finds the date column and the return column (by name, with a positional
    A/B fallback), and lets you override the return column,
  * parses returns that contain '%', thousand separators, '$' or (parentheses)
    negatives,
  * drops blank rows and rows with unparseable dates/returns,
  * auto-detects whether returns are percent or decimal,
  * sorts ascending by date and de-duplicates dates,
  * detects the return frequency (monthly / quarterly / annual / irregular).
"""

from __future__ import annotations

import re
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
    return_column: str | None = None        # name/label of the column used
    date_column: str | None = None          # name/label of the date column used
    candidate_return_columns: list[str] = field(default_factory=list)
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
# Robust numeric parsing
# ---------------------------------------------------------------------------
def clean_numeric(series: pd.Series) -> tuple[pd.Series, bool]:
    """
    Coerce a messy text/number column into floats.

    Handles '%', thousand separators (','), '$', whitespace and accounting-style
    (parentheses) negatives. Returns (values, had_percent_sign) where
    ``had_percent_sign`` is True if any cell carried a literal '%'.
    """
    s = series.astype(str).str.strip()
    had_percent = bool(s.str.contains("%", regex=False).any())

    # Accounting negatives: (1.2) -> -1.2
    neg = s.str.match(r"^\(.*\)$")
    s = s.str.replace(r"[%$,()]", "", regex=True).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "None": np.nan, "-": np.nan})

    vals = pd.to_numeric(s, errors="coerce")
    vals = vals.where(~neg.fillna(False), -vals)
    return vals, had_percent


# ---------------------------------------------------------------------------
# Percent vs decimal detection
# ---------------------------------------------------------------------------
def detect_percent_scale(returns: pd.Series) -> bool:
    """
    Heuristic: decide whether a numeric return column is expressed in PERCENT.

    Periodic asset returns are almost always well under 1.0 in decimal form
    (e.g. 0.02 = 2%). A typical magnitude near or above ~0.5 is implausible as a
    decimal (that is >50% per period) but ordinary as a percentage (1.5 = 1.5%).
    """
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if r.empty:
        return False
    median_abs = float(r.abs().median())
    if median_abs > 0.5:
        return True
    if float(r.abs().quantile(0.90)) > 1.0:
        return True
    if r.std() > 1.0:
        return True
    return False


# ---------------------------------------------------------------------------
# Reading raw cells (csv or excel) + header detection
# ---------------------------------------------------------------------------
def _read_raw(source, sheet_name) -> pd.DataFrame:
    """Read a csv/xlsx source into a raw DataFrame with no header assumption."""
    # Rewind file-like buffers so they can be read more than once.
    if hasattr(source, "seek"):
        try:
            source.seek(0)
        except Exception:  # noqa: BLE001
            pass

    name = getattr(source, "name", source if isinstance(source, str) else "")
    is_csv = isinstance(name, str) and name.lower().endswith(".csv")

    if is_csv:
        return pd.read_csv(source, header=None, dtype=str, skip_blank_lines=True)
    try:
        return pd.read_excel(source, sheet_name=sheet_name, header=None)
    except Exception:  # noqa: BLE001 -- fall back to csv parsing
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_csv(source, header=None, dtype=str, skip_blank_lines=True)


def _looks_like_header(row: pd.Series) -> bool:
    """A row is a header if most cells are non-numeric, non-date labels."""
    cells = [str(c).strip() for c in row.tolist() if str(c).strip() not in ("", "nan")]
    if not cells:
        return False
    label_like = 0
    for c in cells:
        as_num = pd.to_numeric(c.replace(",", "").replace("%", "").replace("$", ""),
                               errors="coerce")
        as_date = pd.to_datetime(c, errors="coerce")
        if pd.isna(as_num) and pd.isna(as_date):
            label_like += 1
    return label_like >= max(1, len(cells) // 2)


# ---------------------------------------------------------------------------
# Column selection
# ---------------------------------------------------------------------------
# Exclude cumulative/benchmark/identifier columns when auto-picking returns.
_RETURN_EXCLUDE = re.compile(
    r"link|cumul|bench|index|since|inception|date|units|market|value|"
    r"mv|accrual|addition|gain|income|fee|modif|account|name|id",
    re.IGNORECASE,
)
_RETURN_INCLUDE = re.compile(r"return|ror|perf|rate of return", re.IGNORECASE)


def _rank_return_col(name: str) -> int:
    """Lower rank = preferred. Prefer net-of-fees, then gross, then generic."""
    n = name.lower()
    if "nof" in n or "net" in n:
        return 0
    if "gof" in n or "gross" in n:
        return 1
    return 2


def _find_columns(
    df: pd.DataFrame,
    has_header: bool,
    date_column,
    return_column,
) -> tuple[object, object, list]:
    """
    Resolve which columns to use for date and return.

    Returns (date_col_key, return_col_key, candidate_return_keys).
    Keys are column labels (header names) or integer positions.
    """
    cols = list(df.columns)

    # ---- date column ----
    if date_column is not None and date_column in cols:
        date_key = date_column
    elif has_header:
        date_key = next(
            (c for c in cols if re.search(r"date", str(c), re.IGNORECASE)), cols[0]
        )
    else:
        date_key = cols[0]

    # ---- candidate return columns ----
    if has_header:
        candidates = [
            c for c in cols
            if c != date_key
            and _RETURN_INCLUDE.search(str(c))
            and not _RETURN_EXCLUDE.search(str(c))
        ]
        candidates = sorted(candidates, key=lambda c: _rank_return_col(str(c)))
    else:
        candidates = []

    # Positional fallback: column B.
    if not candidates:
        fallback = cols[1] if len(cols) > 1 else cols[0]
        candidates = [fallback]

    # ---- chosen return column ----
    if return_column is not None:
        if return_column in cols:
            return_key = return_column
        elif isinstance(return_column, int) and return_column < len(cols):
            return_key = cols[return_column]
        else:
            raise ValueError(
                f"return_column '{return_column}' not found. "
                f"Available columns: {list(cols)}"
            )
    else:
        return_key = candidates[0]

    return date_key, return_key, candidates


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------
def load_returns(
    source,
    sheet_name=0,
    force_percent: bool | None = None,
    declared_frequency: str | None = None,
    return_column=None,
    date_column=None,
) -> ImportResult:
    """
    Load and clean a return stream from an .xlsx or .csv source.

    Parameters
    ----------
    source : str | path | file-like
        Path to the file or an open buffer (e.g. a Streamlit upload).
    sheet_name : str | int
        Worksheet to read for Excel inputs (default: first sheet).
    force_percent : bool | None
        Override percent auto-detection. None = auto-detect.
    declared_frequency : str | None
        Override frequency auto-detection (e.g. "monthly").
    return_column : str | int | None
        Name (or position) of the return column to use. None = auto-pick
        (prefers a net-of-fees periodic return; ignores linked/cumulative
        and benchmark columns).
    date_column : str | None
        Name of the date column. None = auto-detect.

    Returns
    -------
    ImportResult
    """
    messages: list[str] = []

    raw = _read_raw(source, sheet_name)
    if raw.shape[1] < 2:
        raise ValueError(
            "Input must have at least two columns (a date and a return)."
        )

    # Detect & apply a header row.
    has_header = _looks_like_header(raw.iloc[0])
    if has_header:
        header = [str(c).strip() for c in raw.iloc[0].tolist()]
        df = raw.iloc[1:].copy()
        df.columns = header
        messages.append(f"Detected header row: {header}")
    else:
        df = raw.copy()
        messages.append("No header row detected; using column A=date, B=return.")

    df = df.reset_index(drop=True)

    # Resolve columns.
    date_key, return_key, candidates = _find_columns(
        df, has_header, date_column, return_column
    )
    if has_header:
        messages.append(
            f"Using date column '{date_key}' and return column '{return_key}'."
        )
        if len(candidates) > 1:
            messages.append(
                f"Other return columns available: "
                f"{[c for c in candidates if c != return_key]}."
            )

    # Build the working frame.
    work = pd.DataFrame({
        "date": pd.to_datetime(df[date_key], errors="coerce"),
    })
    values, had_percent = clean_numeric(df[return_key])
    work["reported_return"] = values.values

    # Drop blank / invalid rows (need BOTH a valid date and a valid return).
    before = len(work)
    work = work.dropna(subset=["date", "reported_return"]).reset_index(drop=True)
    dropped = before - len(work)
    if dropped:
        messages.append(f"Removed {dropped} blank/invalid row(s).")

    if work.empty:
        raise ValueError("No valid (date, return) rows were found in the input.")

    # Sort ascending and de-duplicate dates (keep last).
    work = work.sort_values("date").reset_index(drop=True)
    dup = work["date"].duplicated().sum()
    if dup:
        work = work.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
        messages.append(f"Removed {dup} duplicate date(s) (kept last).")

    # Flag trailing exact-zero returns (often NAV roll-forwards / not-yet-revalued
    # "copy forward" rows in appraisal data -- they understate volatility).
    trailing_zeros = 0
    for v in work["reported_return"].iloc[::-1]:
        if v == 0:
            trailing_zeros += 1
        else:
            break
    if trailing_zeros:
        messages.append(
            f"NOTE: the last {trailing_zeros} observation(s) have a 0.00% return. "
            "In appraisal/NAV data these are often un-revalued roll-forward rows; "
            "consider excluding them as they artificially dampen volatility."
        )

    # Percent vs decimal: a literal '%' is conclusive; otherwise use the heuristic.
    if force_percent is None:
        is_percent = had_percent or detect_percent_scale(work["reported_return"])
        why = "'%' sign present" if had_percent else "magnitude heuristic"
    else:
        is_percent = force_percent
        why = "user override"
    if is_percent:
        work["reported_return"] = work["reported_return"] / 100.0
        messages.append(f"Returns treated as PERCENT ({why}) -> divided by 100.")
    else:
        messages.append(f"Returns treated as DECIMAL ({why}; no scaling).")

    # Frequency.
    if declared_frequency:
        from .config import ANNUALIZATION_FACTORS

        freq = declared_frequency.lower()
        ppy = ANNUALIZATION_FACTORS.get(freq, 12)
        _, _, median_days = detect_frequency(work["date"])
        messages.append(f"Frequency set by user: {freq} ({ppy}/yr).")
    else:
        freq, ppy, median_days = detect_frequency(work["date"])
        messages.append(
            f"Detected frequency: {freq} ({ppy}/yr; "
            f"median {median_days:.0f} days between observations)."
        )

    if len(work) < 12:
        messages.append(
            f"NOTE: only {len(work)} observations -- the de-smoothing parameter "
            "and statistics will be of limited statistical reliability."
        )

    return ImportResult(
        data=work[["date", "reported_return"]],
        frequency=freq,
        periods_per_year=ppy,
        detected_as_percent=is_percent,
        n_observations=len(work),
        median_days_between=median_days,
        return_column=str(return_key),
        date_column=str(date_key),
        candidate_return_columns=[str(c) for c in candidates],
        messages=messages,
    )
