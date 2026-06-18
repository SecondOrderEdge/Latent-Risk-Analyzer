"""
pdf_report.py
=============

Render a print-ready one-page PDF "IC / DD memo" summarising a run:

  * title + disclaimer
  * run facts (period, frequency, observations, asset class, rho)
  * a plain-English read of the hidden volatility and worst scenario
  * headline metrics table (reported vs de-smoothed)
  * worst stress scenarios table
  * cumulative-growth chart + stress-impact bar chart

Built entirely with matplotlib (already a dependency) so there is nothing new
to install. Output goes to a path or an in-memory buffer.

NOTE: the stress figures are sensitivity-based estimates, not forecasts.
"""

from __future__ import annotations

import io
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .stats import cumulative_growth  # noqa: E402

_BLUE = "#1f77b4"
_RED = "#d62728"
_DARK = "#1b3a5b"


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------
def _pct(x, dp=1, signed=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:+.{dp}%}" if signed else f"{x:.{dp}%}"


def _num(x, dp=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{dp}f}"


def _lookup(summary_table: pd.DataFrame) -> dict:
    return {
        r["Metric"]: (r["Reported"], r["De-smoothed"])
        for _, r in summary_table.iterrows()
    }


# ---------------------------------------------------------------------------
# Inline chart drawing (onto provided axes)
# ---------------------------------------------------------------------------
def _plot_growth(ax, data):
    ax.plot(data["date"], cumulative_growth(data["reported_return"]),
            label="Reported", color=_BLUE, linewidth=1.5)
    ax.plot(data["date"], cumulative_growth(data["desmoothed_return"]),
            label="De-smoothed", color=_RED, linewidth=1.5)
    ax.set_title("Cumulative Growth of $1", fontsize=9, fontweight="bold")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=7)


def _plot_stress(ax, stress_df):
    df = stress_df.sort_values("Scenario impact")
    colors = [_RED if v < 0 else "#2ca02c" for v in df["Scenario impact"]]
    ax.barh(df["Scenario"], df["Scenario impact"], color=colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.6)
    ax.set_title("Stress Test — Estimated Impact by Scenario",
                 fontsize=9, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="x")
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))


# ---------------------------------------------------------------------------
# Table drawing
# ---------------------------------------------------------------------------
def _draw_table(ax, col_labels, rows, title, col_widths=None, font=7.5):
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=9, fontweight="bold", loc="left", color=_DARK)
    tbl = ax.table(cellText=rows, colLabels=col_labels, loc="center",
                   cellLoc="center", colWidths=col_widths)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(font)
    tbl.scale(1, 1.35)
    for (r, _), cell in tbl.get_celld().items():
        cell.set_edgecolor("#CBD9E8")
        if r == 0:
            cell.set_facecolor(_BLUE)
            cell.set_text_props(color="white", fontweight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#EAF2FA")
    return tbl


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build_pdf(
    output,
    data: pd.DataFrame,
    summary_table: pd.DataFrame,
    stress_df: pd.DataFrame,
    assumptions: dict,
    desmooth_meta: dict | None = None,
    periods_per_year: int = 4,
    fund_name: str | None = None,
):
    """Write a one-page PDF report to ``output`` (path or binary buffer)."""
    desmooth_meta = desmooth_meta or {}
    look = _lookup(summary_table)
    vi = summary_table.attrs.get("volatility_inflation")

    d0 = pd.to_datetime(data["date"]).min().date()
    d1 = pd.to_datetime(data["date"]).max().date()

    fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait

    # --- header text ---
    title = "Latent Risk Analyzer — Risk Summary"
    if fund_name:
        # Strip a file extension (e.g. "AL CAP 91.csv" -> "AL CAP 91").
        clean_name = os.path.splitext(str(fund_name))[0].strip()
        if clean_name:
            title += f"  ·  {clean_name}"
    fig.text(0.07, 0.965, title, fontsize=15, fontweight="bold", color=_DARK)
    fig.text(0.07, 0.945,
             "Geltner de-smoothing + private-market stress testing  ·  "
             "stress results are SENSITIVITY-BASED ESTIMATES, not forecasts",
             fontsize=8, style="italic", color="#666666")

    facts1 = (
        f"Period: {d0} to {d1}    |    "
        f"Frequency: {assumptions.get('frequency','?')} "
        f"({assumptions.get('annualization_factor', periods_per_year)}/yr)    |    "
        f"Observations: {desmooth_meta.get('n_observations', len(data))}"
    )
    facts2 = (
        f"Asset class: {assumptions.get('asset_class_preset','—')}    |    "
        f"rho: {desmooth_meta.get('rho_used','?')} "
        f"({desmooth_meta.get('rho_source','?')})"
    )
    fig.text(0.07, 0.927, facts1, fontsize=7.5, color="#333333")
    fig.text(0.07, 0.911, facts2, fontsize=7.5, color="#333333")

    # --- plain-English read ---
    rep_vol, des_vol = look.get("Annualized volatility", (np.nan, np.nan))
    worst = (stress_df.sort_values("Estimated drawdown").iloc[0]
             if stress_df is not None and not stress_df.empty else None)
    read = (
        f"Reported volatility of {_pct(rep_vol)} understates risk: after "
        f"de-smoothing, estimated 'true' volatility is {_pct(des_vol)} "
        f"({_pct(vi, signed=True)} higher)."
    )
    if worst is not None:
        read += (
            f"  The most severe modelled scenario, {worst['Scenario']}, implies "
            f"an estimated drawdown of {_pct(worst['Estimated drawdown'])}."
        )
    fig.text(0.07, 0.895, read, fontsize=8.5, color="#222222", wrap=True,
             ha="left", va="top",
             bbox=dict(boxstyle="round,pad=0.6", fc="#EAF2FA", ec="#CBD9E8"))

    # --- layout for tables + charts ---
    # Tables + growth chart in a gridspec; the horizontal stress-bar chart gets
    # its own axes with a wider left margin so long scenario names fit.
    gs = fig.add_gridspec(
        3, 1, left=0.07, right=0.93, top=0.82, bottom=0.34,
        height_ratios=[0.85, 1.1, 1.4], hspace=0.7,
    )

    # Headline metrics table.
    ax_m = fig.add_subplot(gs[0])
    metric_rows = []
    for label, kind in [("Annualized return", "pct"),
                        ("Annualized volatility", "pct"),
                        ("Sharpe ratio", "num"),
                        ("Max drawdown", "pct")]:
        rep, des = look.get(label, (np.nan, np.nan))
        if kind == "pct":
            metric_rows.append([label, _pct(rep, 2), _pct(des, 2)])
        else:
            metric_rows.append([label, _num(rep), _num(des)])
    metric_rows.append(["Volatility inflation", "", _pct(vi, signed=True)])
    _draw_table(ax_m, ["Metric", "Reported", "De-smoothed"], metric_rows,
                "Headline metrics", col_widths=[0.5, 0.25, 0.25])

    # Worst scenarios table.
    ax_w = fig.add_subplot(gs[1])
    if stress_df is not None and not stress_df.empty:
        worst5 = stress_df.sort_values("Estimated drawdown").head(5)
        wrows = []
        for _, r in worst5.iterrows():
            rec = r["Recovery (years)"]
            wrows.append([
                str(r["Scenario"]),
                _pct(r["Estimated drawdown"]),
                _num(rec, 1) if np.isfinite(rec) else "n/a",
                f"{r['Impact / de-smoothed vol (sd)']:+.1f}σ",
            ])
        _draw_table(ax_w,
                    ["Worst scenarios", "Est. drawdown", "Recovery (yrs)",
                     "vs de-smoothed vol"],
                    wrows, "Worst stress scenarios (sensitivity-based estimates)",
                    col_widths=[0.45, 0.2, 0.18, 0.17])
    else:
        ax_w.axis("off")

    # Charts.
    _plot_growth(fig.add_subplot(gs[2]), data)
    if stress_df is not None and not stress_df.empty:
        ax_stress = fig.add_axes([0.22, 0.06, 0.71, 0.22])
        _plot_stress(ax_stress, stress_df)

    fig.text(0.07, 0.025,
             "Sensitivity-based estimates driven by editable beta assumptions — "
             "not forecasts or investment advice.",
             fontsize=7, style="italic", color="#888888")

    # Save.
    if hasattr(output, "write"):  # file-like
        with PdfPages(output) as pdf:
            pdf.savefig(fig)
    else:
        with PdfPages(output) as pdf:
            pdf.savefig(fig)
    plt.close(fig)
    return output


def pdf_to_bytes(*args, **kwargs) -> bytes:
    """Convenience wrapper: return the PDF report as raw bytes (for downloads)."""
    buf = io.BytesIO()
    build_pdf(buf, *args, **kwargs)
    buf.seek(0)
    return buf.getvalue()
