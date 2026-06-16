"""
make_template.py
================

Generate the blank input template (templates/input_template.xlsx) used for the
new-fund due-diligence workflow, where you build the return stream by hand.

The template matches exactly what the importer expects:
    Sheet "Returns":  Column A = Date, Column B = Reported Return
A separate "Instructions" sheet documents the format. Re-run this script to
regenerate the file after editing.
"""

from __future__ import annotations

import os

import xlsxwriter

EXAMPLE_ROWS = [
    ("2023-03-31", 0.021),
    ("2023-06-30", 0.018),
    ("2023-09-30", -0.004),
    ("2023-12-31", 0.026),
]

INSTRUCTIONS = [
    ("Latent Risk Analyzer — input template", "title"),
    ("", "blank"),
    ("HOW TO USE", "head"),
    ("1. Put one return observation per row on the 'Returns' sheet.", "body"),
    ("2. Column A = period-end Date. Column B = the periodic Reported Return.", "body"),
    ("3. Replace the example rows with your data, then save as .xlsx (or .csv).", "body"),
    ("4. Load it in the app (streamlit run app.py) or CLI (python cli.py file).", "body"),
    ("", "blank"),
    ("FORMAT NOTES", "head"),
    ("• Dates: any spreadsheet-readable date; rows are auto-sorted ascending.", "body"),
    ("• Returns may be DECIMAL (0.021) or PERCENT (2.1%) — units auto-detected.", "body"),
    ("• Be consistent within the column. Don't mix 0.021 and 2.1 in one file.", "body"),
    ("• Frequency (monthly/quarterly/annual) is inferred from the date spacing.", "body"),
    ("• Blank rows are ignored. Keep the date and return columns aligned.", "body"),
    ("• Extra columns to the right are ignored, so you may add notes if useful.", "body"),
    ("", "blank"),
    ("WHAT THIS TOOL DOES", "head"),
    ("Runs Geltner de-smoothing to reveal hidden volatility, then applies", "body"),
    ("sensitivity-based stress scenarios. Stress results are ESTIMATES, not", "body"),
    ("forecasts — they depend on the editable beta assumptions.", "body"),
]


def build(path: str) -> None:
    wb = xlsxwriter.Workbook(path)

    # --- formats ---
    hdr = wb.add_format({"bold": True, "bg_color": "#1f77b4", "font_color": "white",
                         "border": 1, "align": "center"})
    date_fmt = wb.add_format({"num_format": "yyyy-mm-dd", "border": 1})
    ret_fmt = wb.add_format({"num_format": "0.00%", "border": 1})
    note_fmt = wb.add_format({"italic": True, "font_color": "#888888"})
    title_fmt = wb.add_format({"bold": True, "font_size": 14, "font_color": "#1f77b4"})
    head_fmt = wb.add_format({"bold": True})
    body_fmt = wb.add_format({"text_wrap": True})

    # --- Returns sheet (first sheet -> the one the importer reads) ---
    ws = wb.add_worksheet("Returns")
    ws.set_column("A:A", 14)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 30)
    ws.write("A1", "Date", hdr)
    ws.write("B1", "Reported Return", hdr)
    ws.write("C1", "Notes (optional, ignored)", note_fmt)

    for i, (d, r) in enumerate(EXAMPLE_ROWS, start=1):
        ws.write_datetime(i, 0, _as_date(d), date_fmt)
        ws.write_number(i, 1, r, ret_fmt)
    ws.write(len(EXAMPLE_ROWS) + 1, 2,
             "↑ Example rows — replace with your data.", note_fmt)
    ws.freeze_panes(1, 0)

    # --- Instructions sheet ---
    info = wb.add_worksheet("Instructions")
    info.set_column("A:A", 90)
    fmt_map = {"title": title_fmt, "head": head_fmt, "body": body_fmt,
               "blank": body_fmt}
    for row, (text, kind) in enumerate(INSTRUCTIONS):
        info.write(row, 0, text, fmt_map[kind])

    wb.close()


def _as_date(s: str):
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d")


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input_template.xlsx")
    build(out)
    print(f"Wrote template -> {out}")


if __name__ == "__main__":
    main()
