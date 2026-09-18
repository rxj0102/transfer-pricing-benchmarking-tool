"""Tests for tp_benchmarking.cup."""

from __future__ import annotations

import os

import pytest

from tp_benchmarking.cup import (
    CREDIT_SPREAD_BPS,
    IntercompanyLoan,
    benchmark_loan_interest_rate,
    get_risk_free_rate,
)

requires_network = pytest.mark.skipif(
    os.environ.get("TP_BENCHMARKING_SKIP_NETWORK_TESTS") == "1",
    reason="network test disabled via TP_BENCHMARKING_SKIP_NETWORK_TESTS",
)


def test_benchmark_rate_is_risk_free_plus_spread():
    loan = IntercompanyLoan(
        principal=1_000_000.0,
        tenor="5-year",
        borrower_credit_rating="BBB",
        actual_annual_interest_rate=0.0635,  # exactly at the benchmark
    )

    result = benchmark_loan_interest_rate(loan, risk_free_rate=0.0485)

    expected_spread = CREDIT_SPREAD_BPS["BBB"] / 10_000
    assert result.benchmark_rate == pytest.approx(0.0485 + expected_spread)
    assert result.risk_free_rate == pytest.approx(0.0485)
    assert result.credit_spread_bps == CREDIT_SPREAD_BPS["BBB"]


def test_rate_matching_benchmark_is_within_tolerance():
    loan = IntercompanyLoan(
        principal=1_000_000.0,
        tenor="5-year",
        borrower_credit_rating="BBB",
        actual_annual_interest_rate=0.0485 + CREDIT_SPREAD_BPS["BBB"] / 10_000,
    )

    result = benchmark_loan_interest_rate(loan, risk_free_rate=0.0485)

    assert result.difference_bps == pytest.approx(0.0, abs=1e-6)
    assert result.within_tolerance


def test_rate_far_below_benchmark_is_flagged():
    loan = IntercompanyLoan(
        principal=1_000_000.0,
        tenor="5-year",
        borrower_credit_rating="BBB",
        actual_annual_interest_rate=0.045,  # well below the ~6.35% benchmark
    )

    result = benchmark_loan_interest_rate(loan, risk_free_rate=0.0485)

    assert result.difference_bps < -100
    assert not result.within_tolerance


def test_higher_credit_rating_implies_lower_benchmark_rate():
    """A stronger (lower-risk) credit rating should command a lower spread,
    and therefore a lower benchmark interest rate."""
    aaa_loan = IntercompanyLoan(
        principal=1.0, tenor="10-year", borrower_credit_rating="AAA",
        actual_annual_interest_rate=0.05,
    )
    ccc_loan = IntercompanyLoan(
        principal=1.0, tenor="10-year", borrower_credit_rating="CCC",
        actual_annual_interest_rate=0.05,
    )

    aaa_result = benchmark_loan_interest_rate(aaa_loan, risk_free_rate=0.045)
    ccc_result = benchmark_loan_interest_rate(ccc_loan, risk_free_rate=0.045)

    assert aaa_result.benchmark_rate < ccc_result.benchmark_rate


def test_custom_tolerance_is_respected():
    loan = IntercompanyLoan(
        principal=1.0,
        tenor="5-year",
        borrower_credit_rating="BBB",
        actual_annual_interest_rate=0.0485 + CREDIT_SPREAD_BPS["BBB"] / 10_000 + 0.001,
    )  # 10bps above benchmark

    tight = benchmark_loan_interest_rate(loan, risk_free_rate=0.0485, tolerance_bps=5.0)
    loose = benchmark_loan_interest_rate(loan, risk_free_rate=0.0485, tolerance_bps=50.0)

    assert not tight.within_tolerance
    assert loose.within_tolerance


@requires_network
def test_get_risk_free_rate_returns_plausible_live_yield():
    rate = get_risk_free_rate("10-year")
    # Sanity band wide enough to tolerate real market movement without
    # being a meaningless check: Treasury yields have not left roughly
    # this band in decades.
    assert 0.0 < rate < 0.20
