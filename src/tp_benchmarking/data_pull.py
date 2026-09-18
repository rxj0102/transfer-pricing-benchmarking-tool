"""Pull public-company financial data for the comparable set and cache it locally.

Transfer pricing context
-------------------------
Every TNMM benchmarking study starts with a *comparable set*: a group of
independent companies performing functions similar to the tested party,
whose financial results are used to derive an arm's length range. In
practice an economist buys this data from a commercial database (S&P
Capital IQ, Bureau van Dijk/Moody's Orbis, RoyaltyStat, etc.). Those feeds
are licensed and expensive, so this project substitutes Yahoo Finance
(via ``yfinance``) as a free, public proxy for annual income-statement
data. That substitution is itself a limitation worth stating up front:
Yahoo's data is normalized for retail-investor consumption, not audited
for comparability-study purposes, and it does not disclose related-party
revenue mix, segment-level data, or footnote detail the way a commercial
TP database would. See ``README.md`` for the full limitations list.

This module is intentionally "dumb": it only pulls and lightly reshapes
raw data. All comparability judgment (screens, exclusions, PLI math)
lives in the downstream modules so that this module stays a thin,
swappable data-access layer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Comparable set universe
# ---------------------------------------------------------------------------
# Candidate comparables: independent, US-listed (including ADRs) providers of
# IT / business-process outsourcing services. This is the *candidate* list
# fed into the comparability screens in screening.py -- being on this list
# does not mean a company survives the screens. The list was assembled by:
#   1. Identifying public companies whose primary SIC/NAICS classification
#      and Yahoo Finance "industry" tag correspond to IT services
#      (SIC 7379 "Computer Rental and Leasing" / 7389 "Services-Computer
#      Programming, Data Processing, Etc.", NAICS 541512).
#   2. Excluding diversified mega-cap outliers whose revenue scale and
#      business mix are not reasonably comparable to a mid-size offshore
#      IT service delivery entity (e.g. Accenture: ~$65bn revenue,
#      consulting + technology + operations across every industry
#      vertical -- a scale and functional mismatch with a typical tested
#      party in this fact pattern).
#   3. Dropping companies no longer independently public (e.g. WNS Global
#      Services was acquired by Capgemini in 2025 and delisted).
CANDIDATE_TICKERS: list[str] = [
    "EPAM",  # EPAM Systems
    "GLOB",  # Globant
    "DAVA",  # Endava
    "GDYN",  # Grid Dynamics Holdings
    "G",  # Genpact
    "EXLS",  # ExlService Holdings
    "CTSH",  # Cognizant Technology Solutions
    "INFY",  # Infosys (ADR)
    "WIT",  # Wipro (ADR)
    "DXC",  # DXC Technology
]

# Canonical income-statement line items pulled from yfinance's annual
# financials, and the PLI each ultimately feeds (see pli_calculations.py).
INCOME_STATEMENT_FIELDS: dict[str, str] = {
    "Total Revenue": "total_revenue",
    "Operating Income": "operating_income",
    "Gross Profit": "gross_profit",
    "Operating Expense": "operating_expense",
    "Cost Of Revenue": "cost_of_revenue",
}

DEFAULT_CACHE_PATH = Path("data") / "comp_set_financials.csv"
DEFAULT_PROFILE_CACHE_PATH = Path("data") / "comp_set_profiles.csv"


@dataclass(frozen=True)
class CompanyProfile:
    """Static identifying and classification data for one company.

    ``industry`` and ``sector`` are Yahoo Finance's own taxonomy tags,
    used downstream as a (imperfect) proxy for a SIC/NAICS comparability
    screen -- see the module docstring in screening.py for why this is
    treated as a starting point rather than a final answer.
    """

    ticker: str
    company_name: str
    sector: str | None
    industry: str | None
    market_cap: float | None
    currency: str | None
    financial_currency: str | None


# Yahoo Finance ADR tickers trade in USD (``currency`` above) but the
# underlying financial *statements* are frequently reported in the filer's
# home-market currency (``financialCurrency``). Wipro (WIT) reports in INR
# and Endava (DAVA) reports in GBP; every other candidate reports natively
# in USD. This matters for exactly one thing in this project: the
# cross-company *revenue-floor* screen, which compares absolute revenue
# levels and therefore requires a common currency. It does **not** matter
# for the PLIs themselves (Operating Margin, Berry Ratio, Return on Total
# Costs are all ratios of line items within the same statement, so they
# are currency-invariant by construction).
#
# The FX tickers below are Yahoo's own spot-rate series, used as a single
# static conversion rate as of the data-pull date. A real comparability
# study would instead use the average or period-end rate matched to each
# comparable's own fiscal year -- using one static spot rate is a
# simplification, documented here and in screening.py, that is acceptable
# only because FX conversion in this tool affects a single screening
# threshold, not the PLI computation itself.
_FX_TICKER_TO_USD: dict[str, str] = {
    "GBP": "GBPUSD=X",  # already quoted as USD per 1 GBP
    "INR": "INR=X",  # quoted as INR per 1 USD -- must be inverted
}
_FX_INVERTED = {"INR"}


def get_fx_rate_to_usd(currency: str) -> float:
    """Return a spot conversion rate: multiply a native-currency amount by
    this to get an approximate USD amount.

    Parameters
    ----------
    currency:
        Three-letter currency code as reported by Yahoo's
        ``financialCurrency`` field (e.g. ``"USD"``, ``"INR"``, ``"GBP"``).

    Returns
    -------
    float
        ``1.0`` for USD. For a currency in :data:`_FX_TICKER_TO_USD`, the
        latest available spot rate. Unrecognized currencies also return
        ``1.0`` with a logged warning, since silently failing the pull is
        worse than a flagged, approximate screen -- any such case would
        still be visible in the screening log's currency column.
    """
    if currency == "USD" or not currency:
        return 1.0
    fx_ticker = _FX_TICKER_TO_USD.get(currency)
    if fx_ticker is None:
        logger.warning(
            "No FX conversion configured for currency %s; treating as USD "
            "for the revenue-floor screen only (PLIs are unaffected).",
            currency,
        )
        return 1.0
    rate = yf.Ticker(fx_ticker).history(period="5d")["Close"].iloc[-1]
    return 1.0 / rate if currency in _FX_INVERTED else float(rate)


def get_company_profile(ticker: str) -> CompanyProfile:
    """Fetch static profile/classification data for a single ticker.

    Parameters
    ----------
    ticker:
        Exchange ticker symbol, e.g. ``"EPAM"``.

    Returns
    -------
    CompanyProfile
        Identifying fields used for the industry-classification screen
        and for labeling report output. Fields Yahoo does not report are
        returned as ``None`` rather than raising, since a comparability
        screen needs to see -- and flag -- missing data rather than
        crash on it.
    """
    info = yf.Ticker(ticker).info
    return CompanyProfile(
        ticker=ticker,
        company_name=info.get("shortName") or ticker,
        sector=info.get("sector"),
        industry=info.get("industry"),
        market_cap=info.get("marketCap"),
        currency=info.get("currency"),
        financial_currency=info.get("financialCurrency"),
    )


def get_annual_income_statement(ticker: str) -> pd.DataFrame:
    """Fetch annual income-statement line items for one ticker.

    Parameters
    ----------
    ticker:
        Exchange ticker symbol.

    Returns
    -------
    pandas.DataFrame
        One row per fiscal year (most recent first, as returned by
        yfinance), with columns ``fiscal_year_end`` (the period-end date
        actually reported -- comparables in this set do **not** all share
        a December fiscal year end, see ``screening.py``) and the
        canonical line items from ``INCOME_STATEMENT_FIELDS``. A line
        item missing from a given fiscal year is left as ``NaN`` rather
        than dropped or zero-filled, so downstream PLI math can decide
        how to treat it explicitly.
    """
    raw = yf.Ticker(ticker).financials  # rows=line items, columns=period-end dates
    return _reshape_income_statement(raw)


def _reshape_income_statement(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Pure reshaping logic for a raw yfinance ``.financials`` frame.

    Split out from :func:`get_annual_income_statement` so this transform
    -- wide (line item x period) to tidy (one row per fiscal year) --
    can be unit tested with a synthetic frame, without a network call.
    """
    if raw is None or raw.empty:
        logger.warning("No annual financials to reshape")
        return pd.DataFrame(
            columns=["fiscal_year_end", *INCOME_STATEMENT_FIELDS.values()]
        )

    records = []
    for period_end in raw.columns:
        row = {"fiscal_year_end": pd.Timestamp(period_end).date()}
        for raw_label, canonical_name in INCOME_STATEMENT_FIELDS.items():
            value = raw.loc[raw_label, period_end] if raw_label in raw.index else None
            row[canonical_name] = float(value) if pd.notna(value) else float("nan")
        records.append(row)

    df = pd.DataFrame.from_records(records).sort_values(
        "fiscal_year_end", ascending=False
    )
    # A fiscal year with every line item missing carries no information;
    # drop it rather than let it masquerade as a covered year downstream.
    line_item_cols = list(INCOME_STATEMENT_FIELDS.values())
    df = df.dropna(subset=line_item_cols, how="all").reset_index(drop=True)
    return df


def pull_comp_set(
    tickers: list[str] | None = None,
    *,
    use_cache: bool = True,
    cache_path: Path = DEFAULT_CACHE_PATH,
    profile_cache_path: Path = DEFAULT_PROFILE_CACHE_PATH,
) -> pd.DataFrame:
    """Pull (or load cached) financials + profile data for the comp set.

    Parameters
    ----------
    tickers:
        Tickers to pull. Defaults to :data:`CANDIDATE_TICKERS`.
    use_cache:
        If ``True`` (default) and a cache file already exists at
        ``cache_path``, load it instead of calling out to Yahoo Finance.
        This keeps the notebook and tests reproducible even if Yahoo's
        API is unreachable or its schema changes -- the tradeoff, stated
        plainly, is that cached figures go stale as comps file new
        financials. Pass ``use_cache=False`` to force a fresh pull.
    cache_path, profile_cache_path:
        Where to read/write the cached income-statement and profile
        tables.

    Returns
    -------
    pandas.DataFrame
        Long/tidy format: one row per (ticker, fiscal_year_end), with
        company profile columns joined in. This is the single input
        table that ``screening.py`` and ``pli_calculations.py`` consume.
    """
    if use_cache and cache_path.exists() and profile_cache_path.exists():
        logger.info("Loading cached comp set data from %s", cache_path)
        financials = pd.read_csv(cache_path, parse_dates=["fiscal_year_end"])
        financials["fiscal_year_end"] = financials["fiscal_year_end"].dt.date
        profiles = pd.read_csv(profile_cache_path)
        return _add_usd_revenue(financials.merge(profiles, on="ticker", how="left"))

    tickers = tickers or CANDIDATE_TICKERS
    financial_frames = []
    profile_records = []
    for ticker in tickers:
        logger.info("Pulling data for %s", ticker)
        profile = get_company_profile(ticker)
        profile_record = asdict(profile)
        profile_record["fx_rate_to_usd"] = get_fx_rate_to_usd(
            profile.financial_currency or "USD"
        )
        profile_records.append(profile_record)

        statement = get_annual_income_statement(ticker)
        if statement.empty:
            continue
        statement.insert(0, "ticker", ticker)
        financial_frames.append(statement)

    financials = (
        pd.concat(financial_frames, ignore_index=True)
        if financial_frames
        else pd.DataFrame(
            columns=["ticker", "fiscal_year_end", *INCOME_STATEMENT_FIELDS.values()]
        )
    )
    profiles = pd.DataFrame.from_records(profile_records)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    financials.to_csv(cache_path, index=False)
    profiles.to_csv(profile_cache_path, index=False)
    _write_pull_metadata(cache_path.parent / "pull_metadata.json", tickers)

    return _add_usd_revenue(financials.merge(profiles, on="ticker", how="left"))


def _add_usd_revenue(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``total_revenue_usd`` column for the (currency-sensitive)
    revenue-floor screen. All other columns, including ``total_revenue``,
    stay in each comparable's native reporting currency -- that native
    figure, not the USD-converted one, is what feeds the PLI calculations.
    """
    df = df.copy()
    df["total_revenue_usd"] = df["total_revenue"] * df["fx_rate_to_usd"]
    return df


def _write_pull_metadata(path: Path, tickers: list[str]) -> None:
    """Record when/what was pulled, so cached figures carry a visible as-of date."""
    metadata = {
        "pulled_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tickers": tickers,
        "source": "yfinance (Yahoo Finance)",
    }
    path.write_text(json.dumps(metadata, indent=2))


def get_pull_date(cache_dir: Path = Path("data")) -> date | None:
    """Return the as-of date of the cached data pull, if available."""
    metadata_path = cache_dir / "pull_metadata.json"
    if not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text())
    return datetime.fromisoformat(metadata["pulled_at_utc"].rstrip("Z")).date()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = pull_comp_set(use_cache=False)
    print(data.head(20))
    print(f"\nPulled {data['ticker'].nunique()} tickers, {len(data)} company-years.")
