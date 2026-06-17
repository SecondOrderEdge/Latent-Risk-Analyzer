"""
config.py
=========

Central, easy-to-edit configuration for the Latent Risk Analyzer.

Everything a finance professional is likely to want to tweak lives here:

  * default assumptions (risk-free rate, frequency, betas, ...)
  * the sensitivity (beta) unit conventions
  * the historical scenario library
  * the hypothetical scenario library

SIGN / UNIT CONVENTIONS  (read before editing betas!)
-----------------------------------------------------
The stress engine computes a return impact as a sum of
``sensitivity * shock`` terms.  To keep the numbers intuitive for a finance
user, sensitivities and shocks are expressed in the following units:

    equity_beta        return per +1.00 (i.e. +100%) of equity-index return
    credit_beta        return per +100 bps of credit-spread WIDENING (enter <0)
    duration           years of effective duration; price impact = -D * dRate
    inflation_beta     return per +1.00 percentage-point of inflation
    liquidity_beta     return at a full liquidity freeze (intensity = 1.0; <0)
    caprate_beta       return per +100 bps of cap-rate EXPANSION (enter <0)
    nav_markdown_beta  multiplier applied to a scenario's direct NAV markdown

Scenario shocks are expressed as:

    equity        equity-index return (decimal, e.g. -0.40)
    credit_spread credit-spread change in bps (+ = widening)
    rates         interest-rate change in bps (+ = rates up)
    inflation     inflation change in percentage points (+ = inflation up)
    liquidity     liquidity-stress intensity, 0..1 (1 = full freeze)
    cap_rate      cap-rate change in bps (+ = expansion / lower property value)
    nav_markdown  direct private-equity NAV markdown (decimal, e.g. -0.15)
"""

from __future__ import annotations

from copy import deepcopy

# ---------------------------------------------------------------------------
# Annualization factors by detected/declared frequency
# ---------------------------------------------------------------------------
ANNUALIZATION_FACTORS = {
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
    "weekly": 52,
    "daily": 252,
}

# ---------------------------------------------------------------------------
# Default user assumptions
# ---------------------------------------------------------------------------
DEFAULT_ASSUMPTIONS = {
    # --- general ---
    "risk_free_rate": 0.04,        # annual, decimal
    "frequency": "quarterly",      # monthly | quarterly | annual | ...
    "annualization_factor": 4,     # overridden once frequency is known
    "stress_multiplier": 1.0,      # global scaling applied to every scenario
    "asset_class_preset": "Balanced / generic (default)",  # see presets below

    # --- de-smoothing ---
    "rho_override": None,          # if set, used instead of the estimated rho
    "rho_max": 0.95,               # safeguard cap on |rho|

    # --- sensitivities (betas). See unit conventions above. ---
    # Defaults are deliberately conservative/illustrative for a partially
    # market-exposed illiquid fund. They are calibrated so the severe
    # historical scenarios land in a believable (deep but not impossible)
    # range. EDIT THESE for your specific asset.
    "equity_beta": 0.40,           # partial equity participation
    "credit_beta": -0.015,         # loss per +100bps spread widening
    "duration": 2.00,              # years of effective duration
    "inflation_beta": -0.010,      # loss per +1pp inflation surprise
    "liquidity_beta": -0.10,       # loss at a full liquidity freeze
    "caprate_beta": -0.06,         # loss per +100bps cap-rate expansion
    "nav_markdown_beta": 0.40,     # partial pass-through of direct NAV markdowns

    # --- recovery-period estimate ---
    # expected per-PERIOD return used to estimate time-to-recover. If None the
    # engine falls back to the de-smoothed mean periodic return.
    "recovery_return_per_period": None,
}


# ---------------------------------------------------------------------------
# Asset-class sensitivity presets
# ---------------------------------------------------------------------------
# The sensitivity (beta) keys that a preset overrides. Everything else in the
# assumptions dict (risk-free rate, multiplier, ...) is left untouched.
BETA_KEYS = [
    "equity_beta",
    "credit_beta",
    "duration",
    "inflation_beta",
    "liquidity_beta",
    "caprate_beta",
    "nav_markdown_beta",
]

# Ready-made starting points calibrated to each asset class's economics.
# These remain ILLUSTRATIVE -- edit them for the specific fund. Notable choices:
#   * Real estate & infrastructure carry POSITIVE inflation betas (partial
#     inflation hedge via rent/usage-linked revenue).
#   * Private credit (direct lending) carries a slightly NEGATIVE duration
#     because the book is largely floating-rate, so rising rates lift coupon
#     income (a mild benefit), and a large credit-spread beta.
#   * Venture / growth carries a high equity beta, long effective duration
#     (long-dated cashflows hurt by higher rates) and a big lagged NAV markdown.
ASSET_CLASS_PRESETS = {
    "Balanced / generic (default)": {
        "equity_beta": 0.40, "credit_beta": -0.015, "duration": 2.00,
        "inflation_beta": -0.010, "liquidity_beta": -0.10, "caprate_beta": -0.06,
        "nav_markdown_beta": 0.40,
        "notes": "Generic partially market-exposed illiquid fund.",
    },
    "Core real estate": {
        "equity_beta": 0.35, "credit_beta": -0.02, "duration": 3.00,
        "inflation_beta": 0.05, "liquidity_beta": -0.15, "caprate_beta": -0.12,
        "nav_markdown_beta": 0.40,
        "notes": "Cap-rate driven; partial inflation hedge; financing-sensitive.",
    },
    "Private equity (buyout)": {
        "equity_beta": 0.70, "credit_beta": -0.04, "duration": 1.50,
        "inflation_beta": -0.02, "liquidity_beta": -0.12, "caprate_beta": 0.00,
        "nav_markdown_beta": 0.60,
        "notes": "High equity participation + leverage; large lagged NAV markdowns.",
    },
    "Private credit / direct lending": {
        "equity_beta": 0.20, "credit_beta": -0.08, "duration": -0.50,
        "inflation_beta": -0.01, "liquidity_beta": -0.10, "caprate_beta": 0.00,
        "nav_markdown_beta": 0.30,
        "notes": "Spread-driven; mostly floating-rate (rising rates help income).",
    },
    "Infrastructure": {
        "equity_beta": 0.30, "credit_beta": -0.03, "duration": 4.00,
        "inflation_beta": 0.08, "liquidity_beta": -0.10, "caprate_beta": -0.05,
        "nav_markdown_beta": 0.35,
        "notes": "Long-duration, inflation-linked revenues; rate-sensitive.",
    },
    "Venture / growth equity": {
        "equity_beta": 0.80, "credit_beta": -0.02, "duration": 3.00,
        "inflation_beta": -0.04, "liquidity_beta": -0.15, "caprate_beta": 0.00,
        "nav_markdown_beta": 0.70,
        "notes": "Long-duration growth; very illiquid; large delayed markdowns.",
    },
    "Hedge fund / diversified": {
        "equity_beta": 0.40, "credit_beta": -0.03, "duration": 1.00,
        "inflation_beta": -0.02, "liquidity_beta": -0.05, "caprate_beta": 0.00,
        "nav_markdown_beta": 0.20,
        "notes": "More liquid, diversified exposures; smaller markdown lag.",
    },
}


def preset_betas(name: str) -> dict:
    """Return just the beta key/values for a named asset-class preset."""
    if name not in ASSET_CLASS_PRESETS:
        raise KeyError(
            f"Unknown asset-class preset '{name}'. "
            f"Choices: {list(ASSET_CLASS_PRESETS)}"
        )
    preset = ASSET_CLASS_PRESETS[name]
    return {k: preset[k] for k in BETA_KEYS}


def apply_preset(assumptions: dict, name: str) -> dict:
    """Overlay an asset-class preset's betas onto an assumptions dict (in place)."""
    assumptions.update(preset_betas(name))
    return assumptions


# ---------------------------------------------------------------------------
# Historical scenarios
# ---------------------------------------------------------------------------
# Each scenario is a dict of macro shocks. Missing keys default to 0.
# These are *stylised* representations of the episodes, calibrated to broad,
# well-known magnitudes. Treat them as sensitivity inputs, not as exact
# replays of history.
HISTORICAL_SCENARIOS = {
    "Dot-com crash (2000-2002)": {
        "equity": -0.49,      # S&P 500 peak-to-trough ~ -49%
        "credit_spread": 350,
        "rates": -250,        # Fed cut aggressively
        "inflation": -0.5,
        "liquidity": 0.30,
        "cap_rate": 75,
        "nav_markdown": -0.20,
        "description": "Tech/telecom equity collapse, recession, Fed easing.",
    },
    "Global Financial Crisis (2008)": {
        "equity": -0.57,      # S&P 500 ~ -57% peak-to-trough
        "credit_spread": 600,
        "rates": -400,
        "inflation": -1.5,
        "liquidity": 0.90,    # near-total liquidity freeze
        "cap_rate": 250,      # CRE cap rates blew out
        "nav_markdown": -0.35,
        "description": "Systemic credit crisis, severe liquidity freeze, CRE repricing.",
    },
    "COVID crash (2020)": {
        "equity": -0.34,      # fast ~ -34% drawdown
        "credit_spread": 400,
        "rates": -150,
        "inflation": -0.5,
        "liquidity": 0.70,
        "cap_rate": 100,
        "nav_markdown": -0.15,
        "description": "Pandemic shock: sharp, fast drawdown then rapid policy support.",
    },
    "2022 rate / inflation shock": {
        "equity": -0.25,
        "credit_spread": 200,
        "rates": 425,         # ~425 bps of hikes
        "inflation": 5.0,     # CPI surge
        "liquidity": 0.30,
        "cap_rate": 150,
        "nav_markdown": -0.10,
        "description": "Inflation surge and the fastest hiking cycle in decades.",
    },
}


# ---------------------------------------------------------------------------
# Hypothetical scenarios
# ---------------------------------------------------------------------------
HYPOTHETICAL_SCENARIOS = {
    "Interest rates up (+200bps)": {
        "rates": 200, "credit_spread": 50, "cap_rate": 75,
        "description": "Parallel +200bps rate shock.",
    },
    "Interest rates down (-200bps)": {
        "rates": -200, "credit_spread": -25, "cap_rate": -50,
        "description": "Parallel -200bps rate move (easing).",
    },
    "Inflation up (+3pp)": {
        "inflation": 3.0, "rates": 150, "credit_spread": 50,
        "description": "Inflation surprise pushing rates higher.",
    },
    "Inflation down (-2pp)": {
        "inflation": -2.0, "rates": -100,
        "description": "Disinflation / falling price pressures.",
    },
    "Credit spreads widen (+300bps)": {
        "credit_spread": 300, "equity": -0.10, "liquidity": 0.30,
        "description": "Credit risk repricing, mild equity spillover.",
    },
    "Credit spreads tighten (-150bps)": {
        "credit_spread": -150, "equity": 0.05,
        "description": "Risk-on credit rally.",
    },
    "Equity market drawdown (-30%)": {
        "equity": -0.30, "credit_spread": 150, "liquidity": 0.30,
        "nav_markdown": -0.12,
        "description": "Broad equity bear market.",
    },
    "Liquidity freeze": {
        "liquidity": 1.0, "credit_spread": 250, "equity": -0.15,
        "nav_markdown": -0.10,
        "description": "Funding/market liquidity dries up; forced-sale discounts.",
    },
    "Recession": {
        "equity": -0.35, "credit_spread": 350, "rates": -150,
        "inflation": -1.0, "liquidity": 0.40, "cap_rate": 100,
        "nav_markdown": -0.18,
        "description": "Broad cyclical downturn, earnings & NAV declines.",
    },
    "Stagflation": {
        "equity": -0.20, "credit_spread": 250, "rates": 300,
        "inflation": 6.0, "liquidity": 0.40, "cap_rate": 150,
        "nav_markdown": -0.12,
        "description": "High inflation + weak growth; rates up, multiples down.",
    },
    "Soft landing": {
        "equity": 0.08, "credit_spread": -50, "rates": -50,
        "inflation": -1.0,
        "description": "Inflation cools without recession; mild risk-on.",
    },
}


def default_assumptions() -> dict:
    """Return a fresh (deep) copy of the default assumptions dict."""
    return deepcopy(DEFAULT_ASSUMPTIONS)


def all_scenarios() -> dict:
    """Return a merged dict of historical + hypothetical scenarios (copies)."""
    merged = {}
    merged.update(deepcopy(HISTORICAL_SCENARIOS))
    merged.update(deepcopy(HYPOTHETICAL_SCENARIOS))
    return merged
