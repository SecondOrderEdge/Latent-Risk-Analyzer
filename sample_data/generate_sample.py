"""
Generate a synthetic, *smoothed* private-market return stream for testing.

Produces sample_data/sample_returns.xlsx with:
    Column A: Date (quarter-end)
    Column B: Reported return (PERCENT, e.g. 2.1 means 2.1%)

The series is deliberately built with strong positive autocorrelation (an
AR(1)-style smoothing of an underlying "true" return) so the Geltner
de-smoothing has something meaningful to undo.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd


def generate(n_quarters: int = 60, rho: float = 0.45, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Underlying "true" quarterly returns: ~6%/yr mean, ~9%/yr vol.
    true_mean = 0.06 / 4
    true_vol = 0.09 / np.sqrt(4)
    true = rng.normal(true_mean, true_vol, n_quarters)

    # Reported = smoothed (AR(1)-style) version of the true series.
    reported = np.empty(n_quarters)
    reported[0] = true[0]
    for t in range(1, n_quarters):
        reported[t] = rho * reported[t - 1] + (1 - rho) * true[t]

    dates = pd.date_range("2010-03-31", periods=n_quarters, freq="QE")
    return pd.DataFrame({
        "Date": dates,
        "Reported Return (%)": np.round(reported * 100, 4),  # percent form
    })


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    df = generate()
    path = os.path.join(out_dir, "sample_returns.xlsx")
    df.to_excel(path, index=False)
    print(f"Wrote {len(df)} rows -> {path}")


if __name__ == "__main__":
    main()
