# Latent Risk Analyzer

A Python toolkit for **Geltner de-smoothing** and **private-market stress
testing** of appraisal-based / illiquid return streams (real estate, private
equity, private credit, infrastructure, hedge-fund style returns).

Reported private-market returns are typically **smoothed**: they rely on stale
or appraisal-based valuations, so they understate true volatility and overstate
risk-adjusted performance. This tool:

1. **Imports** an Excel return stream and cleans it automatically.
2. **De-smooths** it using Geltner's first-order autocorrelation method to
   reveal the hidden ("latent") volatility.
3. **Stress tests** it against historical and hypothetical macro scenarios
   using editable sensitivity assumptions.
4. **Exports** a multi-tab Excel workbook plus charts.

> ⚠️ **The stress tests are sensitivity-based estimates, not forecasts.** They
> translate macro shocks into estimated return impacts using *your* beta
> assumptions. Their purpose is to reveal hidden volatility and provide a more
> realistic downside-risk framework — not to predict the future.

---

## Installation

```bash
pip install -r requirements.txt
```

Requires Python 3.9+. Core libraries: pandas, numpy, scipy, statsmodels,
matplotlib, openpyxl, XlsxWriter, streamlit.

---

## Input format

Accepts **`.xlsx` or `.csv`**. Two layouts work with no template:

**1. Minimal two-column file** — the common case (e.g. a sheet you build during
due diligence on a new fund).

| Column | Contents                                   |
|--------|--------------------------------------------|
| **A**  | Date (any readable date)                   |
| **B**  | Reported periodic return                   |

A ready-made blank template lives at
[`templates/input_template.xlsx`](templates/input_template.xlsx) (regenerate
with `python templates/make_template.py`). It has the correct headers, example
rows to overwrite, and an Instructions sheet.

**2. Rich vendor exports (e.g. Black Diamond)** — drop the raw export in
directly. The loader finds the date column and the periodic-return column **by
name**, ignoring cumulative/"Linked", benchmark and bookkeeping columns. When a
file has several return streams (e.g. `GOF Return` gross-of-fees and
`NOF Return` net-of-fees) it defaults to **net-of-fees** and lets you switch
(dropdown in the app, `--return-column "GOF Return"` on the CLI).

Common to both:

* A header row is **optional** — it is auto-detected and skipped.
* Returns may be **percent** (`1.5%` / `1.5`) or **decimal** (`0.015`); the
  units are auto-detected. A literal `%` sign is parsed and handled, as are
  thousand separators, `$`, and `(parentheses)` negatives.
* Blank/invalid rows are removed; rows are sorted ascending by date; duplicate
  dates are de-duplicated (last kept).
* Frequency (monthly / quarterly / annual / weekly / daily / irregular) is
  auto-detected from the date spacing.
* Trailing `0.00%` rows (common un-revalued NAV "roll-forward" rows in
  appraisal data) are **flagged** so you can decide whether to exclude them —
  they artificially dampen volatility.

Generate a sample file to try it out:

```bash
python sample_data/generate_sample.py   # -> sample_data/sample_returns.xlsx
```

---

## Usage

### Option 1 — Streamlit app (recommended)

```bash
streamlit run app.py
```

Then in the browser you can:

* upload your `.xlsx`,
* preview the cleaned data and import diagnostics,
* see the **estimated autocorrelation / smoothing parameter (ρ)** and override it,
* edit every **stress-test assumption** (betas, risk-free rate, multiplier, …),
* edit / add **scenarios** in a live table,
* view summary tables and all charts,
* **download** the full Excel workbook.

### Option 2 — Command line

```bash
# Basic run — auto-detect everything, write <input>_analyzed.xlsx next to input
python cli.py sample_data/sample_returns.xlsx

# Override risk-free rate, force quarterly, also save PNG charts
python cli.py data.xlsx --rf 0.045 --frequency quarterly --png-dir charts/

# Pin the smoothing parameter and raise the equity beta
python cli.py data.xlsx --rho 0.40 --equity-beta 0.70
```

Run `python cli.py --help` for the full option list.

---

## What it computes

### Geltner de-smoothing

Reported returns are modelled as a moving average of true returns:

```
r_reported_t = (1 - ρ) * r_true_t + ρ * r_reported_{t-1}
```

Solving for the true (unsmoothed) return gives the de-smoothing formula used by
the tool:

```
r_true_t = (r_reported_t - ρ * r_reported_{t-1}) / (1 - ρ)
```

* **ρ** (the smoothing parameter) is estimated as the lag-1 autocorrelation of
  the reported series; you can override it.
* The **first observation** has no prior period, so its de-smoothed value is
  left equal to the reported value (a defensible, non-fabricated choice).
* **Safeguards**: ρ is floored at 0 if negative (mean reversion, not smoothing),
  capped at `rho_max` (default 0.95) as ρ→1 makes the formula explode, and a
  warning is raised when there are too few observations to trust the estimate.

The result: the **mean** is roughly preserved while **volatility increases** —
the hidden risk is revealed.

### Summary statistics (reported vs de-smoothed)

Annualized return, annualized volatility, Sharpe ratio (user risk-free rate),
max drawdown, best/worst period, lag-1 autocorrelation, skewness and excess
kurtosis — plus the headline **volatility inflation** from de-smoothing.

### Stress testing

Each scenario is a bundle of macro shocks mapped to an estimated return impact
via a linear factor model:

```
impact = stress_multiplier * (
      equity_beta       * equity              # per 1.00 of equity-index return
    + credit_beta       * (credit_spread/100) # per +100 bps spread widening
    - duration          * (rates/10000)       # price ≈ -Duration * Δrate
    + inflation_beta    * inflation           # per +1 pp inflation
    + liquidity_beta    * liquidity           # at full-freeze intensity 1.0
    + caprate_beta      * (cap_rate/100)      # per +100 bps cap-rate expansion
    + nav_markdown_beta * nav_markdown        # direct PE NAV markdown
)
```

For each scenario the engine reports: estimated stressed return, estimated
drawdown, impact in standard deviations of **reported** vs **de-smoothed**
(annualized) volatility, a downside percentile estimate, and a recovery-period
estimate (using a user-defined expected return).

**Historical scenarios:** Dot-com crash, Global Financial Crisis, COVID crash,
2022 rate/inflation shock.

**Hypothetical scenarios:** rates up/down, inflation up/down, spreads
widen/tighten, equity drawdown, liquidity freeze, recession, stagflation, soft
landing — plus any **custom** scenario you add.

---

## Assumptions you can edit

All defaults live in [`latent_risk_analyzer/config.py`](latent_risk_analyzer/config.py)
and can be overridden in the app, on the CLI, or by editing the file:

| Assumption | Meaning / unit |
|---|---|
| `risk_free_rate` | annual risk-free rate (decimal) |
| `frequency` / `annualization_factor` | sampling frequency (auto-detected) |
| `stress_multiplier` | global scaling applied to every scenario |
| `rho_override`, `rho_max` | de-smoothing parameter override and safeguard cap |
| `equity_beta` | return per 1.00 of equity-index return |
| `credit_beta` | return per +100 bps of spread widening (enter < 0) |
| `duration` | effective duration in years |
| `inflation_beta` | return per +1 pp inflation |
| `liquidity_beta` | return at a full liquidity freeze (enter < 0) |
| `caprate_beta` | return per +100 bps cap-rate expansion (enter < 0) |
| `nav_markdown_beta` | multiplier on a scenario's direct NAV markdown |
| `recovery_return_per_period` | expected per-period return for recovery estimates |

> The default betas are **illustrative** for a partially market-exposed
> illiquid fund. **Edit them for your specific asset** — the whole point of the
> tool is to make these assumptions explicit and stress-able.

### Asset-class presets

Rather than start from generic betas every time, pick an asset-class profile as
a calibrated starting point, then fine-tune:

| Preset | Character |
|---|---|
| Balanced / generic | partially market-exposed illiquid fund (the default) |
| Core real estate | cap-rate driven, partial inflation **hedge**, financing-sensitive |
| Private equity (buyout) | high equity + leverage, large lagged NAV markdowns |
| Private credit / direct lending | spread-driven, mostly **floating-rate** (rising rates help income) |
| Infrastructure | long-duration, inflation-linked revenues, rate-sensitive |
| Venture / growth equity | long-duration growth, very illiquid, big delayed markdowns |
| Hedge fund / diversified | more liquid, diversified, smaller markdown lag |

The presets are deliberately differentiated — e.g. a `+200bps` rate shock barely
dents private credit but hits real estate via cap rates and financing, while an
inflation surprise is a *positive* for real estate and infrastructure.

* **App:** choose it from the *Asset-class preset* dropdown; the beta fields
  repopulate and remain editable.
* **CLI:** `python cli.py data.xlsx --asset-class "Core real estate"`
  (individual `--*-beta` flags still override the preset).
* **Code:** `config.ASSET_CLASS_PRESETS` / `config.apply_preset(assumptions, name)`.

These remain illustrative starting points — always tune them for the fund.

---

## Output

The exported workbook (`*_analyzed.xlsx`) contains:

* **Returns** — date, reported, de-smoothed, cumulative growth and drawdown
* **Summary Stats** — reported vs de-smoothed comparison
* **Scenarios** — full stress-test results
* **Assumptions** — every input used (so the run is reproducible) + ρ diagnostics
* **Charts** — embedded PNG charts

Charts (also exportable as standalone PNGs via `--png-dir`): reported vs
de-smoothed series, cumulative growth of $1, drawdown, rolling volatility,
stress-test scenario bars, and a distribution comparison histogram.

---

## Project layout

```
latent_risk_analyzer/
    config.py          # default assumptions + scenario library (edit me!)
    data_import.py     # Excel import, cleaning, frequency & unit detection
    desmoothing.py     # Geltner de-smoothing + safeguards
    stats.py           # summary statistics
    stress_testing.py  # sensitivity-based stress engine
    charts.py          # matplotlib charts
    excel_export.py    # multi-tab .xlsx export
    pipeline.py        # orchestration used by both interfaces
app.py                 # Streamlit interface
cli.py                 # command-line interface
templates/
    make_template.py   # regenerates the blank input template
    input_template.xlsx# ready-to-fill input template (Date + Reported Return)
sample_data/
    generate_sample.py # creates a synthetic smoothed return stream
requirements.txt
```

---

## Disclaimer

This tool is for analytical and educational purposes. The de-smoothed series and
stress-test results are **model-based estimates** that depend heavily on the
chosen parameters (ρ and the sensitivity betas). They are **not** investment
advice or precise forecasts. Always sanity-check the assumptions against your
own knowledge of the underlying asset.
