"""A simpler, second benchmarking module: Comparable Uncontrolled Price
(CUP) for an intercompany loan's interest rate.

Transfer pricing context
-------------------------
TNMM is a *profit-based* method: it infers an arm's length result by
comparing overall profitability to that of independent companies
performing similar functions. The CUP method is different in kind -- it
is a *price-based* method that compares the actual price (here, an
interest rate) charged in a controlled transaction directly to the price
charged in comparable uncontrolled transactions. Per the OECD Guidelines
(para 2.14) and Treas. Reg. §1.482-2(a), CUP is the most direct method
when a genuinely comparable uncontrolled transaction can be identified,
and intercompany loans are one of the more common places to see it used
in practice (OECD Guidelines Chapter X, "Transfer Pricing Aspects of
Financial Transactions," treats loan pricing as a CUP-style exercise
built from a public yield curve plus a credit-spread adjustment).

This module implements exactly that "yield curve + credit spread"
approach, at a level appropriate for a second, illustrative module:

1. Pull a **live, public risk-free base rate** from the relevant point on
   the U.S. Treasury yield curve (via Yahoo Finance Treasury yield
   tickers -- real public market data, not a static assumption).
2. Add a **credit spread** appropriate to the borrower's (assumed) credit
   rating and the loan's tenor.
3. Compare the resulting benchmark rate to the actual intercompany rate.

Limitation, stated plainly: step 2's credit spread table below is a
**static, illustrative** set of typical investment-grade/high-yield
spread relationships, not a live market data feed (a real loan CUP study
would price the spread off current secondary-market bond yields or
loan/CDS spreads for issuers of the same rating and tenor, e.g. via
Bloomberg or a similar terminal). It is included so the mechanics of the
method are demonstrated end-to-end with at least one live, public data
input, not to represent current market credit spreads precisely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import yfinance as yf

Tenor = Literal["13-week", "5-year", "10-year", "30-year"]

# U.S. Treasury yield tickers on Yahoo Finance, by tenor. Chosen to
# bracket typical intercompany loan/working-capital funding maturities.
_TREASURY_TICKERS: dict[Tenor, str] = {
    "13-week": "^IRX",
    "5-year": "^FVX",
    "10-year": "^TNX",
    "30-year": "^TYX",
}

CreditRating = Literal["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]

# Illustrative credit spreads (in basis points) over the matched-tenor
# Treasury yield, by S&P-equivalent long-term issuer credit rating.
# These approximate typical, historically-observed investment-grade and
# high-yield spread relationships and are NOT a live data feed -- see the
# module docstring. A real analysis would substitute current
# secondary-market spread data for bonds of matching rating and tenor.
CREDIT_SPREAD_BPS: dict[CreditRating, float] = {
    "AAA": 40.0,
    "AA": 60.0,
    "A": 90.0,
    "BBB": 150.0,
    "BB": 300.0,
    "B": 450.0,
    "CCC": 700.0,
}


def get_risk_free_rate(tenor: Tenor) -> float:
    """Fetch the current U.S. Treasury yield for the given tenor.

    Parameters
    ----------
    tenor:
        One of ``"13-week"``, ``"5-year"``, ``"10-year"``, ``"30-year"``.

    Returns
    -------
    float
        Annualized yield as a decimal (e.g. ``0.045`` for 4.5%).
    """
    ticker = _TREASURY_TICKERS[tenor]
    history = yf.Ticker(ticker).history(period="5d")
    if history.empty:
        raise RuntimeError(f"No recent price history returned for {ticker}")
    latest_quote = float(history["Close"].iloc[-1])
    return latest_quote / 100.0


@dataclass(frozen=True)
class IntercompanyLoan:
    """A hypothetical intercompany loan, for illustrating the CUP method.

    This is a fictional funding arrangement -- e.g. a working-capital
    loan from the US parent to the hypothetical offshore tested party in
    ``benchmarking.py`` -- invented solely to demonstrate the CUP loan
    interest benchmarking mechanic. See ``README.md``'s disclaimer.
    """

    principal: float
    tenor: Tenor
    borrower_credit_rating: CreditRating
    actual_annual_interest_rate: float


@dataclass(frozen=True)
class LoanBenchmarkResult:
    """Result of benchmarking an intercompany loan's interest rate."""

    loan: IntercompanyLoan
    risk_free_rate: float
    credit_spread_bps: float
    benchmark_rate: float
    difference_bps: float
    within_tolerance: bool
    tolerance_bps: float


def benchmark_loan_interest_rate(
    loan: IntercompanyLoan,
    *,
    tolerance_bps: float = 25.0,
    risk_free_rate: float | None = None,
) -> LoanBenchmarkResult:
    """Benchmark an intercompany loan's rate against a public yield-curve
    + credit-spread CUP.

    Parameters
    ----------
    loan:
        The intercompany loan being tested.
    tolerance_bps:
        How many basis points of difference from the benchmark rate are
        treated as "close enough" to be considered arm's length. Real
        practice does not use a bright-line tolerance band the way an
        interquartile range does for TNMM -- CUP is generally expected to
        match closely given a truly comparable transaction -- so this
        tolerance is a simplification for illustration, not a regulatory
        standard.
    risk_free_rate:
        Override the live-pulled Treasury yield (mainly for testing).
        When omitted, pulled live via :func:`get_risk_free_rate`.

    Returns
    -------
    LoanBenchmarkResult
    """
    rate = (
        risk_free_rate
        if risk_free_rate is not None
        else get_risk_free_rate(loan.tenor)
    )
    spread_bps = CREDIT_SPREAD_BPS[loan.borrower_credit_rating]
    benchmark_rate = rate + spread_bps / 10_000

    difference_bps = (loan.actual_annual_interest_rate - benchmark_rate) * 10_000

    return LoanBenchmarkResult(
        loan=loan,
        risk_free_rate=rate,
        credit_spread_bps=spread_bps,
        benchmark_rate=benchmark_rate,
        difference_bps=difference_bps,
        within_tolerance=abs(difference_bps) <= tolerance_bps,
        tolerance_bps=tolerance_bps,
    )


# A hypothetical working-capital loan from the US parent to the
# hypothetical offshore tested party used elsewhere in this project
# (see benchmarking.HYPOTHETICAL_TESTED_PARTY). Priced deliberately below
# the benchmark rate, so the CUP module has a real "outside tolerance"
# case to walk through, the same way the TNMM tested party was set up to
# fall below its arm's length range.
HYPOTHETICAL_INTERCOMPANY_LOAN = IntercompanyLoan(
    principal=20_000_000.0,
    tenor="5-year",
    borrower_credit_rating="BBB",
    actual_annual_interest_rate=0.045,
)
