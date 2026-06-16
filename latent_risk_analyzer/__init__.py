"""
Latent Risk Analyzer
====================

A toolkit for Geltner de-smoothing and private-market stress testing of
appraisal-based / illiquid return streams.

The package is intentionally modular so a finance professional can re-use any
single piece:

    data_import     -> read & clean an Excel return stream
    desmoothing     -> Geltner first-order de-smoothing
    stats           -> summary statistics (pre / post de-smoothing)
    stress_testing  -> historical & hypothetical sensitivity-based stress tests
    charts          -> matplotlib charts (saved as PNG or returned as figures)
    excel_export    -> multi-tab .xlsx workbook export
    config          -> default assumptions + scenario library

IMPORTANT
---------
The stress tests in this package are *sensitivity-based estimates*, not
precise forecasts. They translate macro shocks into estimated return impacts
using user-editable beta assumptions. Their purpose is to reveal the hidden
volatility that smoothing hides and to give a more realistic downside-risk
framework -- not to predict the future.
"""

from . import config, data_import, desmoothing, stats, stress_testing

__all__ = [
    "config",
    "data_import",
    "desmoothing",
    "stats",
    "stress_testing",
]

__version__ = "1.0.0"
