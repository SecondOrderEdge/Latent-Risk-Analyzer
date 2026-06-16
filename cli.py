#!/usr/bin/env python3
"""
cli.py -- command-line interface for the Latent Risk Analyzer.

Usage
-----
    python cli.py INPUT.xlsx [options]

Examples
--------
    # Basic run, auto-detect everything, write results next to the input:
    python cli.py sample_data/sample_returns.xlsx

    # Override the risk-free rate, force quarterly, save charts as PNGs:
    python cli.py data.xlsx --rf 0.045 --frequency quarterly --png-dir charts/

    # Pin the smoothing parameter and bump equity beta:
    python cli.py data.xlsx --rho 0.4 --equity-beta 0.7

Run ``python cli.py --help`` for the full list of options.

NOTE: stress-test outputs are SENSITIVITY-BASED ESTIMATES, not forecasts.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from latent_risk_analyzer import charts, config, excel_export, pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Geltner de-smoothing + private-market stress testing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Path to the input .xlsx or .csv file (Date + Return).")
    p.add_argument("-o", "--output", help="Output .xlsx path (default: <input>_analyzed.xlsx).")
    p.add_argument("--png-dir", help="If set, also save charts as PNGs into this directory.")

    # Import overrides.
    p.add_argument("--frequency", choices=list(config.ANNUALIZATION_FACTORS),
                   help="Override frequency auto-detection.")
    p.add_argument("--return-column", default=None,
                   help="Name of the return column to use (e.g. 'NOF Return'). "
                        "Default: auto-pick (prefers net-of-fees periodic return).")
    p.add_argument("--date-column", default=None,
                   help="Name of the date column. Default: auto-detect.")
    pct = p.add_mutually_exclusive_group()
    pct.add_argument("--percent", dest="force_percent", action="store_true",
                     help="Force returns to be treated as percentages.")
    pct.add_argument("--decimal", dest="force_percent", action="store_false",
                     help="Force returns to be treated as decimals.")
    p.set_defaults(force_percent=None)

    # General assumptions.
    p.add_argument("--rf", type=float, default=None, help="Annual risk-free rate (decimal).")
    p.add_argument("--stress-multiplier", type=float, default=None,
                   help="Global multiplier applied to every scenario.")

    # De-smoothing.
    p.add_argument("--rho", type=float, default=None, help="Override the smoothing parameter rho.")
    p.add_argument("--rho-max", type=float, default=None, help="Safeguard cap on rho.")

    # Sensitivities (betas).
    p.add_argument("--asset-class", default=None, choices=list(config.ASSET_CLASS_PRESETS),
                   help="Apply an asset-class beta preset as a starting point. "
                        "Individual --*-beta flags below still override it.")
    p.add_argument("--equity-beta", type=float, default=None)
    p.add_argument("--credit-beta", type=float, default=None)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--inflation-beta", type=float, default=None)
    p.add_argument("--liquidity-beta", type=float, default=None)
    p.add_argument("--caprate-beta", type=float, default=None)
    p.add_argument("--nav-markdown-beta", type=float, default=None)
    p.add_argument("--recovery-return", type=float, default=None,
                   help="Expected per-period return used for recovery estimates.")

    p.add_argument("--quiet", action="store_true", help="Suppress console tables.")
    return p


def _assumptions_from_args(args) -> dict:
    a = config.default_assumptions()
    # Apply an asset-class preset first; explicit --*-beta flags below win.
    if args.asset_class:
        config.apply_preset(a, args.asset_class)
    a["asset_class_preset"] = args.asset_class or "Balanced / generic (default)"
    mapping = {
        "rf": "risk_free_rate",
        "stress_multiplier": "stress_multiplier",
        "rho": "rho_override",
        "rho_max": "rho_max",
        "equity_beta": "equity_beta",
        "credit_beta": "credit_beta",
        "duration": "duration",
        "inflation_beta": "inflation_beta",
        "liquidity_beta": "liquidity_beta",
        "caprate_beta": "caprate_beta",
        "nav_markdown_beta": "nav_markdown_beta",
        "recovery_return": "recovery_return_per_period",
    }
    for arg_name, key in mapping.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            a[key] = val
    if args.frequency:
        a["frequency"] = args.frequency
    return a


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    assumptions = _assumptions_from_args(args)

    try:
        res = pipeline.run_analysis(
            args.input,
            assumptions=assumptions,
            force_percent=args.force_percent,
            declared_frequency=args.frequency,
            return_column=args.return_column,
            date_column=args.date_column,
        )
    except Exception as exc:  # noqa: BLE001 -- surface a clean message to the user
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", 20)

    if not args.quiet:
        print("\n=== IMPORT ===")
        for m in res.import_result.messages:
            print("  -", m)
        print("\n=== DE-SMOOTHING ===")
        for k, v in pipeline.desmooth_meta(res).items():
            print(f"  {k}: {v}")
        for w in res.desmooth_result.warnings:
            print("  !", w)

        print("\n=== SUMMARY STATISTICS (reported vs de-smoothed) ===")
        print(res.summary_table.to_string(index=False))
        vi = res.summary_table.attrs.get("volatility_inflation")
        if vi is not None:
            print(f"\n  Volatility inflation from de-smoothing: {vi:+.1%}")

        print("\n=== STRESS TESTS (sensitivity-based estimates, not forecasts) ===")
        show = [c for c in res.stress_df.columns if not c.startswith("contrib_")]
        print(res.stress_df[show].to_string(index=False))

    # Write Excel output.
    out_path = args.output or os.path.splitext(args.input)[0] + "_analyzed.xlsx"
    excel_export.export_workbook(
        out_path,
        data=res.data,
        summary_table=res.summary_table,
        stress_df=res.stress_df,
        assumptions=res.assumptions,
        desmooth_meta=pipeline.desmooth_meta(res),
        periods_per_year=res.periods_per_year,
        include_charts=True,
    )
    print(f"\nWrote workbook -> {out_path}")

    if args.png_dir:
        all_charts = charts.build_all_charts(res.data, res.stress_df, res.periods_per_year)
        paths = charts.save_all_charts(all_charts, args.png_dir)
        print(f"Wrote {len(paths)} PNG chart(s) -> {args.png_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
