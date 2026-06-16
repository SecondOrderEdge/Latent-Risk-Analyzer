"""
app.py -- Streamlit interface for the Latent Risk Analyzer.

Run with:
    streamlit run app.py

Features:
  * upload an .xlsx file (Date in column A, Reported return in column B)
  * preview the cleaned data
  * see the estimated autocorrelation / smoothing parameter (rho) and override it
  * edit all stress-test assumptions (betas, rf, multiplier, ...)
  * edit / add scenarios
  * view summary tables and charts
  * export the full multi-tab Excel workbook

IMPORTANT: stress-test results are SENSITIVITY-BASED ESTIMATES, not forecasts.
"""

from __future__ import annotations

import copy

import pandas as pd
import streamlit as st

from latent_risk_analyzer import (
    charts,
    config,
    data_import,
    desmoothing,
    excel_export,
    stats,
    stress_testing,
)

st.set_page_config(page_title="Latent Risk Analyzer", layout="wide")

st.title("📉 Latent Risk Analyzer")
st.caption(
    "Geltner de-smoothing + private-market stress testing. "
    "**Stress results are sensitivity-based estimates, not forecasts.**"
)


# ---------------------------------------------------------------------------
# Sidebar: upload + import options
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1 · Input")
    uploaded = st.file_uploader(
        "Upload .xlsx or .csv (Date + Return; vendor exports OK)",
        type=["xlsx", "csv"],
    )
    st.markdown("---")
    st.header("Import options")
    freq_choice = st.selectbox(
        "Frequency", ["auto"] + list(config.ANNUALIZATION_FACTORS), index=0,
    )
    pct_choice = st.selectbox(
        "Return units", ["auto-detect", "percent", "decimal"], index=0,
    )

if uploaded is None:
    st.info(
        "👈 Upload an Excel file to begin. "
        "Expected layout: **Column A = Date**, **Column B = Reported return**. "
        "You can generate a sample with `python sample_data/generate_sample.py`."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Import & clean
# ---------------------------------------------------------------------------
force_percent = {"auto-detect": None, "percent": True, "decimal": False}[pct_choice]
declared_freq = None if freq_choice == "auto" else freq_choice

# First pass: auto-detect columns so we can offer a return-column picker.
try:
    imp = data_import.load_returns(
        uploaded, force_percent=force_percent, declared_frequency=declared_freq
    )
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not read the file: {exc}")
    st.stop()

# If the file has several candidate return columns (e.g. a vendor export with
# GOF/NOF), let the user choose which one to analyze and re-import.
if len(imp.candidate_return_columns) > 1:
    with st.sidebar:
        st.markdown("---")
        st.header("Return column")
        chosen_col = st.selectbox(
            "Which return stream?",
            imp.candidate_return_columns,
            index=imp.candidate_return_columns.index(imp.return_column),
            help="Vendor exports often include gross-of-fees (GOF) and "
                 "net-of-fees (NOF) periodic returns.",
        )
    if chosen_col != imp.return_column:
        imp = data_import.load_returns(
            uploaded, force_percent=force_percent,
            declared_frequency=declared_freq, return_column=chosen_col,
        )

st.subheader("2 · Cleaned data preview")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Observations", imp.n_observations)
c2.metric("Frequency", imp.frequency)
c3.metric("Periods / year", imp.periods_per_year)
c4.metric("Units", "percent" if imp.detected_as_percent else "decimal")
with st.expander("Import log"):
    for m in imp.messages:
        st.write("•", m)
st.dataframe(imp.data, use_container_width=True, height=240)


# ---------------------------------------------------------------------------
# Assumptions editor
# ---------------------------------------------------------------------------
st.subheader("3 · Assumptions")
defaults = config.default_assumptions()
ppy = imp.periods_per_year

with st.expander("General & de-smoothing", expanded=True):
    g1, g2, g3 = st.columns(3)
    rf = g1.number_input("Risk-free rate (annual, decimal)", value=float(defaults["risk_free_rate"]),
                         step=0.005, format="%.4f")
    stress_multiplier = g2.number_input("Stress multiplier", value=float(defaults["stress_multiplier"]),
                                        step=0.1, format="%.2f")
    rho_max = g3.number_input("rho max (safeguard cap)", value=float(defaults["rho_max"]),
                              min_value=0.50, max_value=0.999, step=0.01, format="%.3f")

    # Estimate rho so the user can see it before deciding to override.
    rho_est = desmoothing.estimate_rho(imp.data["reported_return"])
    r1, r2 = st.columns([1, 2])
    r1.metric("Estimated rho (lag-1 autocorr.)", f"{rho_est:.3f}")
    override_rho = r2.checkbox("Override rho manually?", value=False)
    if override_rho:
        rho_override = r2.slider("rho override", min_value=-0.5, max_value=0.99,
                                 value=float(min(max(rho_est, 0.0), 0.95)), step=0.01)
    else:
        rho_override = None

with st.expander("Sensitivities (betas)", expanded=True):
    # Asset-class preset: pick a starting profile, then fine-tune below.
    preset_names = list(config.ASSET_CLASS_PRESETS)
    preset_name = st.selectbox(
        "Asset-class preset (starting point — edit the betas below)",
        preset_names, index=0,
    )
    st.caption(f"ℹ️ {config.ASSET_CLASS_PRESETS[preset_name]['notes']}")
    base = config.preset_betas(preset_name)  # repopulates the inputs on switch
    st.caption(
        "Return impact = Σ (sensitivity × shock). See README/config for unit "
        "conventions. Presets are illustrative — edit for your specific fund."
    )
    # Widget keys include the preset name so switching preset refreshes defaults.
    pk = preset_name
    b1, b2, b3, b4 = st.columns(4)
    equity_beta = b1.number_input("Equity beta (per 1.0 eq. return)", value=float(base["equity_beta"]), step=0.05, format="%.3f", key=f"eqb_{pk}")
    credit_beta = b2.number_input("Credit beta (per +100bps)", value=float(base["credit_beta"]), step=0.01, format="%.3f", key=f"crb_{pk}")
    duration = b3.number_input("Duration (years)", value=float(base["duration"]), step=0.25, format="%.2f", key=f"dur_{pk}")
    inflation_beta = b4.number_input("Inflation beta (per +1pp)", value=float(base["inflation_beta"]), step=0.05, format="%.3f", key=f"infb_{pk}")
    b5, b6, b7, b8 = st.columns(4)
    liquidity_beta = b5.number_input("Liquidity beta (at freeze=1)", value=float(base["liquidity_beta"]), step=0.05, format="%.3f", key=f"liqb_{pk}")
    caprate_beta = b6.number_input("Cap-rate beta (per +100bps)", value=float(base["caprate_beta"]), step=0.05, format="%.3f", key=f"capb_{pk}")
    nav_beta = b7.number_input("NAV markdown beta (multiplier)", value=float(base["nav_markdown_beta"]), step=0.1, format="%.2f", key=f"navb_{pk}")
    recovery_return = b8.number_input("Recovery return / period (0=use de-smoothed mean)", value=0.0, step=0.005, format="%.4f")

assumptions = config.default_assumptions()
assumptions.update({
    "risk_free_rate": rf,
    "stress_multiplier": stress_multiplier,
    "rho_max": rho_max,
    "rho_override": rho_override,
    "equity_beta": equity_beta,
    "credit_beta": credit_beta,
    "duration": duration,
    "inflation_beta": inflation_beta,
    "liquidity_beta": liquidity_beta,
    "caprate_beta": caprate_beta,
    "nav_markdown_beta": nav_beta,
    "recovery_return_per_period": (recovery_return or None),
    "asset_class_preset": preset_name,
    "frequency": imp.frequency,
    "annualization_factor": ppy,
})


# ---------------------------------------------------------------------------
# Scenario editor
# ---------------------------------------------------------------------------
st.subheader("4 · Scenarios")
st.caption("Edit shocks directly. Add custom scenarios as new rows.")

scen_dict = config.all_scenarios()
scen_rows = []
for name, scen in scen_dict.items():
    row = {"Scenario": name, "description": scen.get("description", "")}
    for f in stress_testing.FACTORS:
        row[f] = scen.get(f, 0.0)
    scen_rows.append(row)
scen_editor_df = pd.DataFrame(scen_rows)

edited = st.data_editor(
    scen_editor_df, use_container_width=True, num_rows="dynamic", height=420,
    key="scenario_editor",
)


def _scenarios_from_editor(df: pd.DataFrame) -> dict:
    out = {}
    for _, r in df.iterrows():
        name = str(r.get("Scenario", "")).strip()
        if not name:
            continue
        scen = {"description": str(r.get("description", "") or "")}
        for f in stress_testing.FACTORS:
            try:
                scen[f] = float(r.get(f, 0.0) or 0.0)
            except (TypeError, ValueError):
                scen[f] = 0.0
        out[name] = scen
    return out


scenarios = _scenarios_from_editor(edited)


# ---------------------------------------------------------------------------
# Run the analysis
# ---------------------------------------------------------------------------
des = desmoothing.desmooth(
    imp.data, rho_override=assumptions["rho_override"], rho_max=assumptions["rho_max"]
)
data = des.data

for w in des.warnings:
    st.warning(w)
st.info(
    f"rho used = **{des.rho_used:.3f}** ({des.rho_source}); "
    f"estimated = {des.rho_estimated:.3f}"
)

summary_table = stats.comparison_table(data, ppy, assumptions["risk_free_rate"])

rep_vol = stats.annualized_volatility(data["reported_return"], ppy)
des_vol = stats.annualized_volatility(data["desmoothed_return"], ppy)
des_mean = stats.annualized_return(data["desmoothed_return"], ppy)
stress_df = stress_testing.run_stress_tests(
    scenarios, assumptions, rep_vol, des_vol, des_mean, ppy
)


# ---------------------------------------------------------------------------
# Results: tabs
# ---------------------------------------------------------------------------
st.subheader("5 · Results")
tab_stats, tab_scen, tab_charts, tab_export = st.tabs(
    ["📊 Summary stats", "🌪 Scenarios", "📈 Charts", "💾 Export"]
)

with tab_stats:
    vi = summary_table.attrs.get("volatility_inflation")
    if vi is not None:
        st.metric("Volatility inflation from de-smoothing", f"{vi:+.1%}")
    st.dataframe(
        summary_table.style.format({"Reported": "{:.4f}", "De-smoothed": "{:.4f}"}),
        use_container_width=True,
    )

with tab_scen:
    st.caption("⚠️ Sensitivity-based estimates, not forecasts. Sorted worst-first.")
    show = [c for c in stress_df.columns if not c.startswith("contrib_")]
    st.dataframe(stress_df[show], use_container_width=True, height=460)

with tab_charts:
    all_charts = charts.build_all_charts(data, stress_df, ppy)
    cc1, cc2 = st.columns(2)
    items = list(all_charts.items())
    for i, (name, fig) in enumerate(items):
        (cc1 if i % 2 == 0 else cc2).pyplot(fig)

with tab_export:
    st.write("Download the full multi-tab workbook (Returns, Summary, Scenarios, Assumptions, Charts).")
    desm_meta = {
        "rho_estimated": round(des.rho_estimated, 4),
        "rho_used": round(des.rho_used, 4),
        "rho_source": des.rho_source,
        "frequency": imp.frequency,
        "periods_per_year": ppy,
        "n_observations": imp.n_observations,
        "warnings": " | ".join(des.warnings) if des.warnings else "none",
    }
    xlsx_bytes = excel_export.export_to_bytes(
        data=data,
        summary_table=summary_table,
        stress_df=stress_df,
        assumptions=assumptions,
        desmooth_meta=desm_meta,
        periods_per_year=ppy,
        include_charts=True,
    )
    st.download_button(
        "⬇️ Download Excel workbook",
        data=xlsx_bytes,
        file_name="latent_risk_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
