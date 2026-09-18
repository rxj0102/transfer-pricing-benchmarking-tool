"""Tests for tp_benchmarking.screening, using small synthetic comp sets
so each screen's boundary behavior can be checked precisely."""

from __future__ import annotations

import pandas as pd
import pytest

from tp_benchmarking.screening import (
    LOSS_YEAR_MAJORITY_THRESHOLD,
    MA_DISTORTION_YOY_THRESHOLD,
    MIN_AVERAGE_ANNUAL_REVENUE_USD,
    run_comparability_screens,
)


def _make_company_years(
    ticker: str,
    company_name: str,
    industry: str,
    revenues: list[float],
    operating_incomes: list[float],
    fiscal_years: list[str] | None = None,
    financial_currency: str = "USD",
    fx_rate_to_usd: float = 1.0,
) -> pd.DataFrame:
    fiscal_years = fiscal_years or [
        f"{2021 + i}-12-31" for i in range(len(revenues))
    ]
    n = len(revenues)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "fiscal_year_end": pd.to_datetime(fiscal_years),
            "total_revenue": revenues,
            "operating_income": operating_incomes,
            "gross_profit": [r * 0.3 for r in revenues],
            "operating_expense": [r * 0.15 for r in revenues],
            "cost_of_revenue": [r * 0.7 for r in revenues],
            "company_name": [company_name] * n,
            "sector": ["Technology"] * n,
            "industry": [industry] * n,
            "financial_currency": [financial_currency] * n,
            "fx_rate_to_usd": [fx_rate_to_usd] * n,
            "total_revenue_usd": [r * fx_rate_to_usd for r in revenues],
        }
    )


def test_healthy_comparable_passes_all_screens():
    comp_set = _make_company_years(
        "AAA",
        "Alpha Services",
        "Information Technology Services",
        revenues=[100_000_000, 105_000_000, 110_000_000, 115_000_000],
        operating_incomes=[10_000_000, 11_000_000, 12_000_000, 13_000_000],
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["AAA"]
    assert row["industry_screen_pass"]
    assert row["revenue_screen_pass"]
    assert row["loss_year_screen_pass"]
    assert row["included"]
    assert "AAA" in result.final_comp_set


def test_industry_mismatch_without_override_fails():
    comp_set = _make_company_years(
        "ZZZ",
        "Zeta Retail",
        "Grocery Stores",
        revenues=[100_000_000] * 4,
        operating_incomes=[5_000_000] * 4,
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["ZZZ"]
    assert not row["industry_screen_pass"]
    assert not row["included"]
    assert "ZZZ" not in result.final_comp_set
    assert "Grocery Stores" in row["exclusion_reason"]


def test_manual_industry_override_passes_despite_mismatch():
    comp_set = _make_company_years(
        "DAVA",
        "Endava plc",
        "Software - Infrastructure",  # deliberately mismatched, like real data
        revenues=[100_000_000] * 4,
        operating_incomes=[5_000_000] * 4,
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["DAVA"]
    assert row["industry_screen_pass"]
    assert "functional review" in row["industry_screen_note"]
    assert row["included"]


def test_revenue_below_floor_fails_screen():
    comp_set = _make_company_years(
        "TINY",
        "Tiny Micro Cap",
        "Information Technology Services",
        revenues=[10_000_000] * 4,  # below MIN_AVERAGE_ANNUAL_REVENUE_USD
        operating_incomes=[1_000_000] * 4,
    )
    assert 10_000_000 < MIN_AVERAGE_ANNUAL_REVENUE_USD

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["TINY"]
    assert not row["revenue_screen_pass"]
    assert not row["included"]


def test_revenue_screen_uses_usd_converted_revenue_for_non_usd_reporter():
    # Native-currency revenue is huge (as with INR), but the USD-converted
    # figure is what the screen should actually test against.
    comp_set = _make_company_years(
        "FXCO",
        "FX Reporter",
        "Information Technology Services",
        revenues=[9_000_000_000] * 4,  # e.g. INR, huge native number
        operating_incomes=[900_000_000] * 4,
        financial_currency="INR",
        fx_rate_to_usd=0.01,  # -> $90,000,000 USD, above the floor
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["FXCO"]
    assert row["avg_annual_revenue_usd"] == pytest.approx(90_000_000)
    assert row["revenue_screen_pass"]


def test_persistent_loss_maker_excluded_majority_threshold():
    # 3 of 4 years are losses -> exceeds 50% majority threshold -> excluded.
    comp_set = _make_company_years(
        "LOSS",
        "Loss Co",
        "Information Technology Services",
        revenues=[100_000_000] * 4,
        operating_incomes=[-1, -1, -1, 1_000_000],
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["LOSS"]
    assert row["loss_years"] == 3
    assert row["loss_year_fraction"] == pytest.approx(0.75)
    assert not row["loss_year_screen_pass"]
    assert not row["included"]


def test_exactly_half_loss_years_survives_majority_test():
    # 2 of 4 years are losses = 50%, which is NOT a majority (> 50%
    # required), so this comparable should survive the screen.
    comp_set = _make_company_years(
        "TIE",
        "Tie Co",
        "Information Technology Services",
        revenues=[100_000_000] * 4,
        operating_incomes=[-1, -1, 1_000_000, 1_000_000],
    )
    assert LOSS_YEAR_MAJORITY_THRESHOLD == 0.5

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["TIE"]
    assert row["loss_year_fraction"] == pytest.approx(0.5)
    assert row["loss_year_screen_pass"]
    assert row["included"]


def test_ma_distorted_year_flagged_and_excluded_from_pli_average_only():
    comp_set = _make_company_years(
        "MNA",
        "M&A Co",
        "Information Technology Services",
        # +80% YoY jump in year 2 -- classic acquisition-driven step change.
        revenues=[100_000_000, 180_000_000, 190_000_000, 195_000_000],
        operating_incomes=[10_000_000, 15_000_000, 16_000_000, 17_000_000],
    )
    assert MA_DISTORTION_YOY_THRESHOLD == 0.30

    result = run_comparability_screens(comp_set)

    distorted_years = result.company_year_log[
        result.company_year_log["ticker"] == "MNA"
    ].sort_values("fiscal_year_end")
    flags = distorted_years["ma_distortion_flag"].tolist()
    assert flags == [False, True, False, False]
    assert distorted_years["included_in_pli_average"].tolist() == [
        True,
        False,
        True,
        True,
    ]
    # The company itself is NOT excluded wholesale -- only the one year is.
    row = result.company_log.set_index("ticker").loc["MNA"]
    assert row["included"]


def test_related_party_screen_is_documented_not_a_gate():
    comp_set = _make_company_years(
        "AAA",
        "Alpha Services",
        "Information Technology Services",
        revenues=[100_000_000] * 4,
        operating_incomes=[10_000_000] * 4,
    )

    result = run_comparability_screens(comp_set)

    row = result.company_log.set_index("ticker").loc["AAA"]
    assert row["related_party_screen_status"] == "Not evaluated (see note)"
    assert "not disclosed" in row["related_party_screen_note"]
    # It never blocks inclusion by itself.
    assert row["included"]


def test_first_year_has_no_growth_rate_and_is_not_flagged():
    comp_set = _make_company_years(
        "AAA",
        "Alpha Services",
        "Information Technology Services",
        revenues=[100_000_000, 105_000_000],
        operating_incomes=[10_000_000, 11_000_000],
    )

    result = run_comparability_screens(comp_set)

    first_year = result.company_year_log.sort_values("fiscal_year_end").iloc[0]
    assert pd.isna(first_year["yoy_revenue_growth"])
    assert not first_year["ma_distortion_flag"]
    assert first_year["included_in_pli_average"]
