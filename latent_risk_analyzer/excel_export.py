"""
excel_export.py
===============

Write a multi-tab .xlsx workbook with:

  * Returns        -> date, reported, de-smoothed, cumulative growth, drawdown
  * Summary Stats  -> reported vs de-smoothed comparison
  * Scenarios      -> stress-test results
  * Assumptions    -> the inputs used (so the run is reproducible)
  * Charts         -> embedded PNG charts (if matplotlib figures are supplied)

Uses xlsxwriter for nice number formats and image embedding.
"""

from __future__ import annotations

import io

import pandas as pd

from .charts import build_all_charts
from .stats import cumulative_growth, drawdown_series


def _assumptions_frame(assumptions: dict) -> pd.DataFrame:
    rows = [{"Assumption": k, "Value": v} for k, v in assumptions.items()]
    return pd.DataFrame(rows)


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
    """
    Write the full workbook to ``output`` (a path or a binary buffer).

    Returns the output object (handy when it is an in-memory BytesIO buffer).
    """
    # Enriched returns tab.
    returns_tab = data.copy()
    returns_tab["cum_growth_reported"] = cumulative_growth(data["reported_return"]).values
    returns_tab["cum_growth_desmoothed"] = cumulative_growth(data["desmoothed_return"]).values
    returns_tab["drawdown_reported"] = drawdown_series(data["reported_return"]).values
    returns_tab["drawdown_desmoothed"] = drawdown_series(data["desmoothed_return"]).values

    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        wb = writer.book

        pct_fmt = wb.add_format({"num_format": "0.00%"})
        num_fmt = wb.add_format({"num_format": "0.0000"})
        hdr_fmt = wb.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
        title_fmt = wb.add_format({"bold": True, "font_size": 14})
        wrap_fmt = wb.add_format({"text_wrap": True, "valign": "top"})

        # ---- Returns tab ----
        returns_tab.to_excel(writer, sheet_name="Returns", index=False)
        ws = writer.sheets["Returns"]
        ws.set_column("A:A", 12)
        ws.set_column("B:C", 14, pct_fmt)
        ws.set_column("D:E", 16, num_fmt)
        ws.set_column("F:G", 16, pct_fmt)
        for col, name in enumerate(returns_tab.columns):
            ws.write(0, col, name, hdr_fmt)

        # ---- Summary Stats tab ----
        summary_table.to_excel(writer, sheet_name="Summary Stats", index=False)
        ws = writer.sheets["Summary Stats"]
        ws.set_column("A:A", 26)
        ws.set_column("B:C", 16, num_fmt)
        for col, name in enumerate(summary_table.columns):
            ws.write(0, col, name, hdr_fmt)
        vol_inf = summary_table.attrs.get("volatility_inflation")
        if vol_inf is not None:
            ws.write(len(summary_table) + 2, 0, "Volatility inflation (de-smoothed/reported - 1):")
            ws.write(len(summary_table) + 2, 1, vol_inf, pct_fmt)
        ws.write(
            len(summary_table) + 4, 0,
            "NOTE: De-smoothing reveals volatility that smoothing hides. "
            "Higher de-smoothed vol/drawdown is expected and intended.",
            wrap_fmt,
        )

        # ---- Scenarios tab ----
        if stress_df is not None and not stress_df.empty:
            # Drop the per-factor contribution columns from the headline view.
            display_cols = [c for c in stress_df.columns if not c.startswith("contrib_")]
            stress_df[display_cols].to_excel(writer, sheet_name="Scenarios", index=False)
            ws = writer.sheets["Scenarios"]
            ws.set_column("A:A", 28)
            ws.set_column("B:B", 40, wrap_fmt)
            ws.set_column("C:J", 18, num_fmt)
            for col, name in enumerate(display_cols):
                ws.write(0, col, name, hdr_fmt)
            note_row = len(stress_df) + 2
            ws.write(
                note_row, 0,
                "SENSITIVITY-BASED ESTIMATES -- not forecasts. Results are driven "
                "by the editable beta assumptions on the Assumptions tab.",
                wrap_fmt,
            )

        # ---- Assumptions tab ----
        adf = _assumptions_frame(assumptions)
        adf.to_excel(writer, sheet_name="Assumptions", index=False)
        ws = writer.sheets["Assumptions"]
        ws.set_column("A:A", 30)
        ws.set_column("B:B", 18)
        for col, name in enumerate(adf.columns):
            ws.write(0, col, name, hdr_fmt)
        if desmooth_meta:
            start = len(adf) + 2
            ws.write(start, 0, "De-smoothing diagnostics", title_fmt)
            for i, (k, v) in enumerate(desmooth_meta.items(), start=start + 1):
                ws.write(i, 0, k)
                ws.write(i, 1, str(v))

        # ---- Charts tab ----
        if include_charts:
            ws = wb.add_worksheet("Charts")
            ws.write(0, 0, "Latent Risk Analyzer -- Charts", title_fmt)
            charts = build_all_charts(data, stress_df, periods_per_year)
            row = 2
            for name, fig in charts.items():
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
                buf.seek(0)
                ws.write(row, 0, name)
                ws.insert_image(row + 1, 0, f"{name}.png",
                                {"image_data": buf, "x_scale": 0.9, "y_scale": 0.9})
                row += 26  # leave vertical room for each image

    return output


def export_to_bytes(*args, **kwargs) -> bytes:
    """Convenience wrapper: return the workbook as raw bytes (for downloads)."""
    buf = io.BytesIO()
    export_workbook(buf, *args, **kwargs)
    buf.seek(0)
    return buf.getvalue()
