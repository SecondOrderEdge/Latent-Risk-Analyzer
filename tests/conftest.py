"""Shared pytest fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def smoothed_returns() -> pd.DataFrame:
    """An AR(1)-smoothed quarterly return series with known positive autocorr."""
    rng = np.random.default_rng(0)
    n, rho = 80, 0.5
    true = rng.normal(0.015, 0.04, n)
    rep = np.empty(n)
    rep[0] = true[0]
    for t in range(1, n):
        rep[t] = rho * rep[t - 1] + (1 - rho) * true[t]
    dates = pd.date_range("2010-03-31", periods=n, freq="QE")
    return pd.DataFrame({"date": dates, "reported_return": rep})


@pytest.fixture
def xlsx_file(tmp_path, smoothed_returns) -> str:
    """The smoothed series written as an .xlsx with friendly headers."""
    p = tmp_path / "returns.xlsx"
    df = smoothed_returns.rename(
        columns={"date": "Date", "reported_return": "Reported Return"}
    )
    df.to_excel(p, index=False)
    return str(p)


@pytest.fixture
def black_diamond_csv(tmp_path) -> str:
    """A vendor-style CSV: many columns, % strings, GOF+NOF return streams."""
    rows = [
        "Date,Units,BMV,EMV,GOF Return,GOF Linked,NOF Return,NOF Linked,Bench",
        '1/3/2023,"4,182",0,"4,182",-0.40%,-0.40%,-0.50%,-0.50%,0.00%',
        '4/3/2023,"4,178","4,182","4,178",4.30%,3.80%,4.20%,3.70%,0.00%',
        '7/3/2023,"5,507","4,178","5,507",1.90%,5.70%,1.80%,5.60%,0.00%',
        '10/2/2023,"7,866","5,507","7,866",1.20%,6.90%,1.10%,6.80%,0.00%',
        '1/2/2024,"7,957","7,866","7,957",1.90%,9.00%,1.80%,8.90%,0.00%',
    ]
    p = tmp_path / "bd.csv"
    p.write_text("\n".join(rows) + "\n")
    return str(p)
