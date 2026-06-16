"""
excel_export.py
===============

Write a polished, finance-friendly multi-tab .xlsx workbook:

  * Overview       -> one-page dashboard: headline metrics, worst scenarios,
                      key charts and a plain-English read (the landing tab)
  * Returns        -> date, reported, de-smoothed, growth of $1, drawdown
  * Summary Stats  -> reported vs de-smoothed comparison (per-metric formats)
  * Scenarios      -> stress-test results (colour-scaled, %-formatted)
  * Assumptions    -> the inputs used (friendly labels + units)
  * Charts         -> embedded PNG charts

Uses xlsxwriter for number formats, conditional formatting and images.
"""

from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd

from . import charts as _charts
from .stats import cumulative_growth, drawdown_series

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
_BLUE = "#1f77b4"
_DARK = "#1b3a5b"
_HDR_BG = "#1f77b4"
_BAND = "#EAF2FA"
_RED = "#C0504D"
_GREEN = "#4F8A4F"

# Which summary metrics are percentages / ratios / counts (for formatting).
_PCT_METRICS = {
    "Annualized return", "Annualized volatility", "Max drawdown",
    "Best period", "Worst period", "Mean period return",
    "Period volatility (std)",
}
_INT_METRICS = {"Observations"}

# Friendly labels + value type for the Assumptions tab.
_ASSUMPTION_LABELS = {
    "risk_free_rate": ("Risk-free rate (annual)", "pct"),
    "frequency": ("Return frequency", "text"),
    "annualization_factor": ("Periods per year", "int"),
    "stress_multiplier": ("Stress multiplier", "num"),
    "rho_override": ("Rho override", "num_or_auto"),
    "rho_max": ("Rho cap (safeguard)", "num"),
    "equity_beta": ("Equity beta (per 1.0 equity return)", "num"),
    "credit_beta": ("Credit beta (per +100 bps spread)", "num"),
    "duration": ("Duration (years)", "num"),
    "inflation_beta": ("Inflation beta (per +1 pp)", "num"),
    "liquidity_beta": ("Liquidity beta (full freeze)", "num"),
    "caprate_beta": ("Cap-rate beta (per +100 bps)", "num"),
    "nav_markdown_beta": ("NAV markdown beta (multiplier)", "num"),
    "recovery_return_per_period": ("Recovery return / period", "pct_or_auto"),
    "asset_class_preset": ("Asset-class preset", "text"),
}

_RETURNS_LABELS = {
    "date": "Date",
    "reported_return": "Reported Return",
    "desmoothed_return": "De-smoothed Return",
    "cum_growth_reported": "Growth of $1 (Reported)",
    "cum_growth_desmoothed": "Growth of $1 (De-smoothed)",
    "drawdown_reported": "Drawdown (Reported)",
    "drawdown_desmoothed": "Drawdown (De-smoothed)",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _is_bad(x) -> bool:
    """True for None / NaN / inf (values Excel can't store as a number)."""
    if x is None:
        return True
    try:
        return not math.isfinite(float(x))
    except (TypeError, ValueError):
        return True


def _summary_lookup(summary_table: pd.DataFrame) -> dict:
    """Map metric name -> (reported, desmoothed)."""
    return {
        row["Metric"]: (row["Reported"], row["De-smoothed"])
        for _, row in summary_table.iterrows()
    }


def _fig_to_buf(fig, dpi=110):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Overview dashboard
# ---------------------------------------------------------------------------
def _write_overview(wb, fmts, data, summary_table, stress_df, assumptions,
                    desmooth_meta):
    ws = wb.add_worksheet("Overview")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 2)
    ws.set_column("B:B", 30)
    ws.set_column("C:D", 18)
    ws.set_column("E:G", 16)

    ws.merge_range("B2:G2", "Latent Risk Analyzer — Overview", fmts["title"])
    ws.merge_range(
        "B3:G3",
        "Geltner de-smoothing + private-market stress testing  ·  "
        "stress results are SENSITIVITY-BASED ESTIMATES, not forecasts",
        fmts["subtitle"],
    )

    # --- run facts ---
    d0 = pd.to_datetime(data["date"]).min().date()
    d1 = pd.to_datetime(data["date"]).max().date()
    facts = [
        ("Period", f"{d0}  to  {d1}"),
        ("Frequency", f"{assumptions.get('frequency','?')} "
                      f"({assumptions.get('annualization_factor','?')}/yr)"),
        ("Observations", str(desmooth_meta.get("n_observations", len(data)))),
        ("Asset-class preset", str(assumptions.get("asset_class_preset", "—"))),
        ("Smoothing ρ (used)", f"{desmooth_meta.get('rho_used','?')} "
                               f"({desmooth_meta.get('rho_source','?')})"),
    ]
    r = 4
    for k, v in facts:
        ws.write(r, 1, k, fmts["lbl"])
        ws.merge_range(r, 2, r, 6, v, fmts["val"])
        r += 1

    # --- headline metrics table ---
    look = _summary_lookup(summary_table)
    r += 1
    ws.merge_range(r, 1, r, 3, "Headline metrics", fmts["section"])
    r += 1
    ws.write(r, 1, "Metric", fmts["thdr"])
    ws.write(r, 2, "Reported", fmts["thdr"])
    ws.write(r, 3, "De-smoothed", fmts["thdr"])
    r += 1
    head_rows = [
        ("Annualized return", "pct"),
        ("Annualized volatility", "pct"),
        ("Sharpe ratio", "num"),
        ("Max drawdown", "pct"),
    ]
    for metric, kind in head_rows:
        rep, des = look.get(metric, (np.nan, np.nan))
        f = fmts["pct2"] if kind == "pct" else fmts["num2"]
        ws.write(r, 1, metric, fmts["lbl"])
        _w(ws, r, 2, rep, f, fmts)
        _w(ws, r, 3, des, f, fmts)
        r += 1

    # The headline number: volatility inflation.
    vol_inf = summary_table.attrs.get("volatility_inflation")
    r += 1
    ws.merge_range(r, 1, r, 3,
                   "Hidden volatility revealed (de-smoothed vs reported)",
                   fmts["lbl"])
    _w(ws, r, 4, vol_inf, fmts["big_pct"], fmts)
    r += 2

    # --- worst stress scenarios ---
    ws.merge_range(r, 1, r, 4,
                   "Worst stress scenarios (estimated drawdown)", fmts["section"])
    r += 1
    ws.write(r, 1, "Scenario", fmts["thdr"])
    ws.write(r, 2, "Est. drawdown", fmts["thdr"])
    ws.write(r, 3, "Recovery (yrs)", fmts["thdr"])
    ws.write(r, 4, "vs de-smoothed vol", fmts["thdr"])
    r += 1
    worst = stress_df.sort_values("Estimated drawdown").head(5)
    for _, row in worst.iterrows():
        ws.write(r, 1, row["Scenario"], fmts["lbl"])
        _w(ws, r, 2, row["Estimated drawdown"], fmts["pct1"], fmts)
        _w(ws, r, 3, row["Recovery (years)"], fmts["num1"], fmts)
        _w(ws, r, 4, row["Impact / de-smoothed vol (sd)"], fmts["sd"], fmts)
        r += 1

    # --- plain-English read ---
    r += 1
    rep_vol = look.get("Annualized volatility", (np.nan, np.nan))[0]
    des_vol = look.get("Annualized volatility", (np.nan, np.nan))[1]
    worst_row = worst.iloc[0] if len(worst) else None
    msg = (
        f"Reported volatility of {_pct(rep_vol)} understates risk: after "
        f"de-smoothing, estimated 'true' volatility is {_pct(des_vol)} "
        f"({_pct(vol_inf, signed=True)} higher). "
    )
    if worst_row is not None:
        msg += (
            f"The most severe modelled scenario, '{worst_row['Scenario']}', "
            f"implies an estimated drawdown of {_pct(worst_row['Estimated drawdown'])}. "
        )
    msg += ("These figures are sensitivity-based estimates driven by the editable "
            "assumptions on the Assumptions tab — tune them for this fund.")
    ws.merge_range(r, 1, r + 3, 6, msg, fmts["note"])
    r += 5

    # --- two key charts ---
    try:
        fig1 = _charts.cumulative_growth_chart(data)
        ws.insert_image(r, 1, "growth.png",
                        {"image_data": _fig_to_buf(fig1), "x_scale": 0.62,
                         "y_scale": 0.62})
        fig2 = _charts.stress_bar_chart(stress_df, "Scenario impact")
        ws.insert_image(r, 5, "stress.png",
                        {"image_data": _fig_to_buf(fig2), "x_scale": 0.62,
                         "y_scale": 0.62})
    except Exception:  # noqa: BLE001 -- charts are a nicety, never fatal
        pass


def _pct(x, signed=False):
    if _is_bad(x):
        return "n/a"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


# ---------------------------------------------------------------------------
# Value writer (handles None/NaN/inf gracefully)
# ---------------------------------------------------------------------------
def _w(ws, row, col, value, num_fmt, fmts, na_text="n/a"):
    if _is_bad(value):
        ws.write(row, col, na_text, fmts["na"])
    else:
        ws.write_number(row, col, float(value), num_fmt)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------
def export_workbook(
    output,
    data: pd.DataFrame,
    summary_table: pd.DataFrame,
    stress_df: pd.DataFrame,
    assumptions: dict,
    desmooth_meta: dict | None = None,
    periods_per_year: int = 4,
    include_charts: bool = True,
):
    """Write the full workbook to ``output`` (a path or binary buffer)."""
    desmooth_meta = desmooth_meta or {}

    # Enriched returns frame.
    returns_tab = data.copy()
    returns_tab["cum_growth_reported"] = cumulative_growth(data["reported_return"]).values
    returns_tab["cum_growth_desmoothed"] = cumulative_growth(data["desmoothed_return"]).values
    returns_tab["drawdown_reported"] = drawdown_series(data["reported_return"]).values
    returns_tab["drawdown_desmoothed"] = drawdown_series(data["desmoothed_return"]).values

    with pd.ExcelWriter(output, engine="xlsxwriter",
                        datetime_format="yyyy-mm-dd") as writer:
        wb = writer.book
        fmts = _make_formats(wb)

        # ---- Overview (first / landing tab) ----
        _write_overview(wb, fmts, data, summary_table, stress_df,
                        assumptions, desmooth_meta)

        # ---- Returns ----
        _write_returns(wb, fmts, returns_tab)

        # ---- Summary Stats ----
        _write_summary(wb, fmts, summary_table)

        # ---- Scenarios ----
        if stress_df is not None and not stress_df.empty:
            _write_scenarios(wb, fmts, stress_df)

        # ---- Assumptions ----
        _write_assumptions(wb, fmts, assumptions, desmooth_meta)

        # ---- Charts ----
        if include_charts:
            _write_charts(wb, fmts, data, stress_df, periods_per_year)

    return output


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------
def _make_formats(wb) -> dict:
    return {
        "title": wb.add_format({"bold": True, "font_size": 18,
                                "font_color": _DARK}),
        "subtitle": wb.add_format({"italic": True, "font_size": 10,
                                   "font_color": "#666666"}),
        "section": wb.add_format({"bold": True, "font_size": 12,
                                  "font_color": _DARK, "bottom": 2,
                                  "border_color": _BLUE}),
        "thdr": wb.add_format({"bold": True, "font_color": "white",
                               "bg_color": _HDR_BG, "border": 1,
                               "align": "center", "valign": "vcenter"}),
        "lbl": wb.add_format({"bold": True, "font_color": _DARK}),
        "val": wb.add_format({"font_color": "#333333"}),
        "na": wb.add_format({"font_color": "#999999", "align": "center",
                             "italic": True}),
        "note": wb.add_format({"text_wrap": True, "valign": "top",
                               "font_color": "#444444", "bg_color": _BAND,
                               "border": 1, "border_color": "#CBD9E8"}),
        "pct2": wb.add_format({"num_format": "0.00%"}),
        "pct1": wb.add_format({"num_format": "0.0%"}),
        "big_pct": wb.add_format({"num_format": "+0.0%", "bold": True,
                                  "font_size": 16, "font_color": _RED}),
        "num2": wb.add_format({"num_format": "0.00"}),
        "num3": wb.add_format({"num_format": "0.000"}),
        "num1": wb.add_format({"num_format": "0.0"}),
        "num0": wb.add_format({"num_format": "0"}),
        "sd": wb.add_format({"num_format": '0.0"σ"'}),
        "growth": wb.add_format({"num_format": "0.000"}),
        "date": wb.add_format({"num_format": "yyyy-mm-dd"}),
        "wrap": wb.add_format({"text_wrap": True, "valign": "top"}),
    }


# ---------------------------------------------------------------------------
# Individual sheets
# ---------------------------------------------------------------------------
def _write_returns(wb, fmts, returns_tab):
    ws = wb.add_worksheet("Returns")
    cols = list(returns_tab.columns)
    labels = [_RETURNS_LABELS.get(c, c) for c in cols]
    for j, lab in enumerate(labels):
        ws.write(0, j, lab, fmts["thdr"])

    col_fmt = {}
    for j, c in enumerate(cols):
        if c == "date":
            col_fmt[j] = fmts["date"]
        elif c.startswith("cum_growth"):
            col_fmt[j] = fmts["growth"]
        else:  # returns + drawdowns
            col_fmt[j] = fmts["pct2"]

    for i in range(len(returns_tab)):
        for j, c in enumerate(cols):
            v = returns_tab.iloc[i, j]
            if c == "date":
                ws.write_datetime(i + 1, j, pd.to_datetime(v).to_pydatetime(),
                                  fmts["date"])
            else:
                _w(ws, i + 1, j, v, col_fmt[j], fmts)

    ws.set_column(0, 0, 12)
    ws.set_column(1, len(cols) - 1, 18)
    ws.freeze_panes(1, 1)
    ws.autofilter(0, 0, len(returns_tab), len(cols) - 1)


def _write_summary(wb, fmts, summary_table):
    ws = wb.add_worksheet("Summary Stats")
    ws.set_column("A:A", 26)
    ws.set_column("B:C", 16)
    ws.write(0, 0, "Metric", fmts["thdr"])
    ws.write(0, 1, "Reported", fmts["thdr"])
    ws.write(0, 2, "De-smoothed", fmts["thdr"])

    for i, (_, row) in enumerate(summary_table.iterrows(), start=1):
        metric = row["Metric"]
        ws.write(i, 0, metric, fmts["lbl"])
        if metric in _INT_METRICS:
            f = fmts["num0"]
        elif metric in _PCT_METRICS:
            f = fmts["pct2"]
        else:
            f = fmts["num2"]
        _w(ws, i, 1, row["Reported"], f, fmts)
        _w(ws, i, 2, row["De-smoothed"], f, fmts)

    n = len(summary_table)
    vol_inf = summary_table.attrs.get("volatility_inflation")
    ws.write(n + 2, 0, "Volatility inflation (de-smoothed / reported − 1)",
             fmts["lbl"])
    _w(ws, n + 2, 1, vol_inf, fmts["pct1"], fmts)
    ws.merge_range(
        n + 4, 0, n + 6, 2,
        "Reading the table: de-smoothing removes appraisal smoothing, so the "
        "de-smoothed series shows HIGHER volatility / drawdown and LOWER "
        "autocorrelation. That is expected and is the point — it reveals the "
        "risk that smoothing hides.",
        fmts["note"],
    )
    ws.freeze_panes(1, 1)


def _write_scenarios(wb, fmts, stress_df):
    ws = wb.add_worksheet("Scenarios")
    # Curated, friendly column set (drop redundant Recovery-periods & raw contribs).
    spec = [
        ("Scenario", "Scenario", "text", 30),
        ("Description", "Description", "wrap", 46),
        ("Stressed return (est.)", "Stressed return (est.)", "pct1", 16),
        ("Scenario impact", "Estimated impact", "pct1", 15),
        ("Estimated drawdown", "Estimated drawdown", "pct1", 16),
        ("Impact / reported vol (sd)", "vs reported vol", "sd", 14),
        ("Impact / de-smoothed vol (sd)", "vs de-smoothed vol", "sd", 16),
        ("Downside percentile", "Downside %ile", "pctile", 13),
        ("Recovery (years)", "Recovery (yrs)", "num1", 13),
    ]
    for j, (_, label, _, width) in enumerate(spec):
        ws.write(0, j, label, fmts["thdr"])
        ws.set_column(j, j, width, fmts["wrap"] if label == "Description" else None)

    for i, (_, row) in enumerate(stress_df.iterrows(), start=1):
        for j, (src, _, kind, _) in enumerate(spec):
            v = row.get(src)
            if kind == "text":
                ws.write(i, j, str(v), fmts["lbl"])
            elif kind == "wrap":
                ws.write(i, j, str(v), fmts["wrap"])
            elif kind == "pctile":
                # stored 0..100 -> show as 0..100 with one decimal
                _w(ws, i, j, v, fmts["num1"], fmts)
            else:
                _w(ws, i, j, v, fmts[kind], fmts)

    n = len(stress_df)
    # Colour-scale the impact & drawdown columns (red = worse, green = better).
    for col_label in ("Estimated impact", "Estimated drawdown"):
        cidx = [s[1] for s in spec].index(col_label)
        ws.conditional_format(
            1, cidx, n, cidx,
            {"type": "3_color_scale", "min_color": _RED,
             "mid_color": "#FFEB84", "max_color": _GREEN},
        )

    ws.merge_range(
        n + 2, 0, n + 3, 8,
        "SENSITIVITY-BASED ESTIMATES — not forecasts. Each scenario maps macro "
        "shocks to an estimated impact via the editable betas on the Assumptions "
        "tab. 'vs vol' columns express the impact in standard deviations of "
        "annualized volatility; a low downside %ile = a severe tail event.",
        fmts["note"],
    )
    ws.freeze_panes(1, 1)
    ws.autofilter(0, 0, n, len(spec) - 1)


def _write_assumptions(wb, fmts, assumptions, desmooth_meta):
    ws = wb.add_worksheet("Assumptions")
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 22)
    ws.write(0, 0, "Assumption", fmts["thdr"])
    ws.write(0, 1, "Value", fmts["thdr"])

    r = 1
    for key, (label, kind) in _ASSUMPTION_LABELS.items():
        if key not in assumptions:
            continue
        val = assumptions[key]
        ws.write(r, 0, label, fmts["lbl"])
        if kind in ("text",):
            ws.write(r, 1, str(val))
        elif kind == "int":
            _w(ws, r, 1, val, fmts["num0"], fmts)
        elif kind == "pct":
            _w(ws, r, 1, val, fmts["pct2"], fmts)
        elif kind == "pct_or_auto":
            if val is None:
                ws.write(r, 1, "auto (de-smoothed mean)", fmts["na"])
            else:
                _w(ws, r, 1, val, fmts["pct2"], fmts)
        elif kind == "num_or_auto":
            if val is None:
                ws.write(r, 1, "auto (estimated)", fmts["na"])
            else:
                _w(ws, r, 1, val, fmts["num2"], fmts)
        else:  # plain numbers (betas, multipliers) -> 3 dp to keep small betas
            _w(ws, r, 1, val, fmts["num3"], fmts)
        r += 1

    # Any extra assumption keys we didn't have an explicit label for.
    for key, val in assumptions.items():
        if key in _ASSUMPTION_LABELS:
            continue
        ws.write(r, 0, key, fmts["lbl"])
        ws.write(r, 1, str(val))
        r += 1

    if desmooth_meta:
        r += 1
        ws.merge_range(r, 0, r, 1, "De-smoothing diagnostics", fmts["section"])
        r += 1
        for k, v in desmooth_meta.items():
            ws.write(r, 0, k.replace("_", " ").capitalize(), fmts["lbl"])
            ws.write(r, 1, str(v))
            r += 1
    ws.freeze_panes(1, 0)


def _write_charts(wb, fmts, data, stress_df, periods_per_year):
    ws = wb.add_worksheet("Charts")
    ws.hide_gridlines(2)
    ws.merge_range("A1:H1", "Latent Risk Analyzer — Charts", fmts["title"])
    charts = _charts.build_all_charts(data, stress_df, periods_per_year)
    titles = {
        "return_series": "Reported vs De-smoothed Returns",
        "cumulative_growth": "Cumulative Growth of $1",
        "drawdown": "Drawdown (Underwater)",
        "rolling_volatility": "Rolling Annualized Volatility",
        "distribution": "Return Distribution",
        "stress_drawdown": "Stress Test — Estimated Drawdown",
        "stress_impact": "Stress Test — Estimated Impact",
    }
    row = 2
    for name, fig in charts.items():
        ws.write(row, 0, titles.get(name, name), fmts["section"])
        ws.insert_image(row + 1, 0, f"{name}.png",
                        {"image_data": _fig_to_buf(fig), "x_scale": 0.9,
                         "y_scale": 0.9})
        row += 26


def export_to_bytes(*args, **kwargs) -> bytes:
    """Convenience wrapper: return the workbook as raw bytes (for downloads)."""
    buf = io.BytesIO()
    export_workbook(buf, *args, **kwargs)
    buf.seek(0)
    return buf.getvalue()
