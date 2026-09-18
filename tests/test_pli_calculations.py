"""Tests for tp_benchmarking.pli_calculations."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from tp_benchmarking.pli_calculations import (
    compute_annual_plis,
    compute_weighted_average_plis,
)


def test_compute_annual_plis_matches_hand_calculation():
    df = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "total_revenue": [1000.0],
            "operating_income": [100.0],
            "gross_profit": [400.0],
            "operating_expense": [300.0],
            "cost_of_revenue": [600.0],
        }
    )

    result = compute_annual_plis(df)

    assert result.loc[0, "operating_margin"] == pytest.approx(100 / 1000)
    assert result.loc[0, "berry_ratio"] == pytest.approx(400 / 300)
    # Total costs = cost_of_revenue + operating_expense = 900
    assert result.loc[0, "return_on_total_costs"] == pytest.approx(100 / 900)


def test_compute_annual_plis_nan_for_zero_denominator():
    df = pd.DataFrame(
        {
            "ticker": ["ZERO"],
            "total_revenue": [0.0],
            "operating_income": [10.0],
            "gross_profit": [50.0],
            "operating_expense": [0.0],
            "cost_of_revenue": [0.0],
        }
    )

    result = compute_annual_plis(df)

    assert math.isnan(result.loc[0, "operating_margin"])
    assert math.isnan(result.loc[0, "berry_ratio"])
    assert math.isnan(result.loc[0, "return_on_total_costs"])


def test_weighted_average_sums_numerator_and_denominator_first():
    # Two years, deliberately different in size, to distinguish "average
    # of ratios" (would give 0.15) from "ratio of sums" (should give the
    # revenue-weighted figure below).
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "total_revenue": [100.0, 900.0],
            "operating_income": [20.0, 90.0],  # margins: 0.20 and 0.10
            "gross_profit": [40.0, 300.0],
            "operating_expense": [30.0, 250.0],
            "cost_of_revenue": [60.0, 600.0],
        }
    )
    annual = compute_annual_plis(df)

    weighted = compute_weighted_average_plis(annual)

    expected_operating_margin = (20.0 + 90.0) / (100.0 + 900.0)  # 0.11
    assert weighted.loc[0, "operating_margin"] == pytest.approx(
        expected_operating_margin
    )
    # A naive average-of-ratios would have given (0.20 + 0.10) / 2 = 0.15,
    # which is NOT what we expect here.
    assert weighted.loc[0, "operating_margin"] != pytest.approx(0.15)


def test_weighted_average_excludes_ma_distorted_years_by_default():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "total_revenue": [100.0, 900.0],
            "operating_income": [20.0, 900.0],  # year 2 is a wild outlier
            "gross_profit": [40.0, 300.0],
            "operating_expense": [30.0, 250.0],
            "cost_of_revenue": [60.0, 600.0],
            "included_in_pli_average": [True, False],
        }
    )
    annual = compute_annual_plis(df)

    weighted = compute_weighted_average_plis(annual)

    # Only year 1 should count.
    assert weighted.loc[0, "years_used"] == 1
    assert weighted.loc[0, "operating_margin"] == pytest.approx(20.0 / 100.0)


def test_weighted_average_can_include_all_years_when_requested():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "total_revenue": [100.0, 900.0],
            "operating_income": [20.0, 90.0],
            "gross_profit": [40.0, 300.0],
            "operating_expense": [30.0, 250.0],
            "cost_of_revenue": [60.0, 600.0],
            "included_in_pli_average": [True, False],
        }
    )
    annual = compute_annual_plis(df)

    weighted = compute_weighted_average_plis(annual, only_included_years=False)

    assert weighted.loc[0, "years_used"] == 2


def test_weighted_average_handles_multiple_tickers_independently():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "total_revenue": [1000.0, 500.0],
            "operating_income": [100.0, 25.0],
            "gross_profit": [400.0, 200.0],
            "operating_expense": [300.0, 150.0],
            "cost_of_revenue": [600.0, 300.0],
        }
    )
    annual = compute_annual_plis(df)

    weighted = compute_weighted_average_plis(annual)

    tickers = set(weighted["ticker"])
    assert tickers == {"AAA", "BBB"}
    bbb_row = weighted.set_index("ticker").loc["BBB"]
    assert bbb_row["operating_margin"] == pytest.approx(25 / 500)


def test_weighted_average_returns_nan_when_no_usable_years():
    df = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "total_revenue": [0.0],
            "operating_income": [10.0],
            "gross_profit": [40.0],
            "operating_expense": [0.0],
            "cost_of_revenue": [0.0],
        }
    )
    annual = compute_annual_plis(df)

    weighted = compute_weighted_average_plis(annual)

    assert math.isnan(weighted.loc[0, "operating_margin"])
    assert math.isnan(weighted.loc[0, "berry_ratio"])
    assert math.isnan(weighted.loc[0, "return_on_total_costs"])
