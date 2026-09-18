"""Tests for tp_benchmarking.data_pull.

The reshaping/FX-conversion logic is tested with synthetic data (fast,
deterministic, no network). The one live-network test is marked so it can
be skipped in offline environments (e.g. CI without internet egress) while
still being available to run locally as the "prove it against real
tickers" smoke test the project plan calls for.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from tp_benchmarking.data_pull import (
    INCOME_STATEMENT_FIELDS,
    _add_usd_revenue,
    _reshape_income_statement,
    get_fx_rate_to_usd,
)

requires_network = pytest.mark.skipif(
    os.environ.get("TP_BENCHMARKING_SKIP_NETWORK_TESTS") == "1",
    reason="network test disabled via TP_BENCHMARKING_SKIP_NETWORK_TESTS",
)


def test_reshape_income_statement_maps_known_fields():
    raw = pd.DataFrame(
        {
            pd.Timestamp("2024-12-31"): {
                "Total Revenue": 100.0,
                "Operating Income": 10.0,
                "Gross Profit": 40.0,
                "Operating Expense": 30.0,
                "Cost Of Revenue": 60.0,
                "Some Unrelated Line": 999.0,
            },
            pd.Timestamp("2023-12-31"): {
                "Total Revenue": 90.0,
                "Operating Income": 8.0,
                "Gross Profit": 35.0,
                "Operating Expense": 27.0,
                "Cost Of Revenue": 55.0,
                "Some Unrelated Line": 999.0,
            },
        }
    )

    result = _reshape_income_statement(raw)

    assert list(result.columns) == [
        "fiscal_year_end",
        *INCOME_STATEMENT_FIELDS.values(),
    ]
    # Most recent fiscal year first.
    assert result.iloc[0]["fiscal_year_end"].isoformat() == "2024-12-31"
    assert result.iloc[0]["total_revenue"] == 100.0
    assert result.iloc[1]["operating_income"] == 8.0


def test_reshape_income_statement_leaves_missing_field_as_nan():
    raw = pd.DataFrame(
        {
            pd.Timestamp("2024-12-31"): {
                "Total Revenue": 100.0,
                "Operating Income": 10.0,
                # Gross Profit, Operating Expense, Cost Of Revenue absent.
            },
        }
    )

    result = _reshape_income_statement(raw)

    assert result.iloc[0]["total_revenue"] == 100.0
    assert pd.isna(result.iloc[0]["gross_profit"])


def test_reshape_income_statement_drops_all_nan_years():
    raw = pd.DataFrame(
        {
            pd.Timestamp("2024-12-31"): {"Total Revenue": 100.0},
            pd.Timestamp("2020-12-31"): {},  # nothing reported at all
        }
    )

    result = _reshape_income_statement(raw)

    assert len(result) == 1
    assert result.iloc[0]["fiscal_year_end"].isoformat() == "2024-12-31"


def test_reshape_income_statement_handles_empty_input():
    result = _reshape_income_statement(pd.DataFrame())
    assert result.empty
    assert list(result.columns) == [
        "fiscal_year_end",
        *INCOME_STATEMENT_FIELDS.values(),
    ]

    result_none = _reshape_income_statement(None)
    assert result_none.empty


def test_get_fx_rate_to_usd_is_noop_for_usd():
    assert get_fx_rate_to_usd("USD") == 1.0
    assert get_fx_rate_to_usd("") == 1.0


def test_get_fx_rate_to_usd_returns_one_for_unrecognized_currency():
    # Unrecognized currency should degrade gracefully (flagged via logging,
    # not a crash) rather than break the whole pull.
    assert get_fx_rate_to_usd("XYZ") == 1.0


def test_add_usd_revenue_converts_using_fx_rate():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "total_revenue": [1000.0, 500.0],
            "fx_rate_to_usd": [1.0, 2.0],
        }
    )

    result = _add_usd_revenue(df)

    assert result.loc[0, "total_revenue_usd"] == 1000.0
    assert result.loc[1, "total_revenue_usd"] == 1000.0


@requires_network
def test_live_pull_for_epam_has_expected_shape():
    """Smoke test against a real ticker, per the project's build process."""
    from tp_benchmarking.data_pull import get_annual_income_statement

    statement = get_annual_income_statement("EPAM")

    assert not statement.empty
    assert "total_revenue" in statement.columns
    # EPAM is profitable and Dec fiscal-year-end; both should hold on
    # every fiscal year actually returned.
    assert (statement["total_revenue"] > 0).all()
    assert all(d.month == 12 for d in statement["fiscal_year_end"])
