"""Tests for tp_benchmarking.benchmarking."""

from __future__ import annotations

import pandas as pd
import pytest

from tp_benchmarking.benchmarking import (
    TestedParty,
    assess_position,
    compute_arms_length_range,
    compute_primary_adjustment,
)


def _weighted_plis(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": list(values.keys()), "operating_margin": list(values.values())}
    )


def test_regulatory_range_matches_hand_calculation_n8():
    # 8 comparables, values 1..8 (as percentages). n * 0.25 = 2 (exact) ->
    # average of the 2nd and 3rd values. n * 0.75 = 6 (exact) -> average
    # of the 6th and 7th values.
    values = {f"T{i}": float(i) for i in range(1, 9)}  # 1.0 .. 8.0
    df = _weighted_plis(values)

    rng = compute_arms_length_range(df, "operating_margin", list(values.keys()))

    assert rng.q1 == pytest.approx((2.0 + 3.0) / 2)
    assert rng.q3 == pytest.approx((6.0 + 7.0) / 2)
    assert rng.median == pytest.approx((4.0 + 5.0) / 2)


def test_regulatory_and_interpolated_methods_can_diverge():
    # With n=8 and non-uniformly spaced values, the regulatory (rank-based,
    # averaging two adjacent ranks) and linear-interpolation methods can
    # give different Q1/Q3 -- verifying the implementation isn't
    # accidentally just calling np.percentile under a different name.
    values = {
        "A": 1.0, "B": 2.0, "C": 3.0, "D": 40.0,
        "E": 41.0, "F": 42.0, "G": 43.0, "H": 100.0,
    }
    df = _weighted_plis(values)

    rng = compute_arms_length_range(df, "operating_margin", list(values.keys()))

    # Regulatory: n*0.25=2 (exact) -> avg(2nd,3rd) = avg(2,3) = 2.5
    assert rng.q1 == pytest.approx(2.5)
    # Interpolated (numpy linear): rank=(n-1)*0.25=1.75 -> interpolate
    # between index 1 (value 2.0) and index 2 (value 3.0) at 0.75 ->
    # 2.0 + 0.75*(3.0-2.0) = 2.75
    assert rng.q1_interpolated == pytest.approx(2.75)
    assert rng.q1 != pytest.approx(rng.q1_interpolated)


def test_regulatory_range_rounds_up_for_non_exact_position():
    # n=9: 9*0.25=2.25 (not exact) -> ceil to 3 -> 3rd smallest value.
    values = {f"T{i}": float(i) for i in range(1, 10)}  # 1.0 .. 9.0
    df = _weighted_plis(values)

    rng = compute_arms_length_range(df, "operating_margin", list(values.keys()))

    assert rng.q1 == pytest.approx(3.0)
    assert rng.q3 == pytest.approx(7.0)


def test_range_only_uses_final_comp_set_tickers():
    values = {"A": 1.0, "B": 2.0, "C": 3.0, "EXCLUDED": 9999.0}
    df = _weighted_plis(values)

    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C"])

    assert rng.n_comparables == 3
    assert 9999.0 not in [v for _, v in rng.values]


def test_range_raises_below_minimum_comparable_count():
    values = {"A": 1.0, "B": 2.0}
    df = _weighted_plis(values)

    with pytest.raises(ValueError, match="at least 3"):
        compute_arms_length_range(df, "operating_margin", list(values.keys()))


def test_range_drops_nan_plis_before_counting():
    # 4 tickers in the final comp set, but one has a NaN PLI (e.g. a zero
    # operating-expense denominator) -- only 3 usable values remain,
    # which should just barely succeed (>= 3 minimum).
    df = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D"],
            "operating_margin": [0.10, 0.12, float("nan"), 0.14],
        }
    )

    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])

    assert rng.n_comparables == 3
    assert "C" not in [ticker for ticker, _ in rng.values]


def test_range_raises_when_nan_plis_drop_below_minimum():
    df = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "operating_margin": [0.10, float("nan"), float("nan")],
        }
    )

    with pytest.raises(ValueError, match="Only 1"):
        compute_arms_length_range(df, "operating_margin", ["A", "B", "C"])


def test_assess_position_within_range():
    df = _weighted_plis({"A": 0.05, "B": 0.10, "C": 0.15, "D": 0.20})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])

    result = assess_position(0.12, rng)

    assert result.in_range
    assert result.position == "within range"


def test_assess_position_below_range():
    df = _weighted_plis({"A": 0.05, "B": 0.10, "C": 0.15, "D": 0.20})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])

    result = assess_position(0.01, rng)

    assert not result.in_range
    assert result.position == "below range"


def test_assess_position_above_range():
    df = _weighted_plis({"A": 0.05, "B": 0.10, "C": 0.15, "D": 0.20})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])

    result = assess_position(0.50, rng)

    assert not result.in_range
    assert result.position == "above range"


def test_primary_adjustment_none_when_in_range():
    df = _weighted_plis({"A": 0.05, "B": 0.10, "C": 0.15, "D": 0.20})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])
    tested_party = TestedParty(
        name="In-range Co", fiscal_year=2025, revenue=1000.0, operating_income=125.0
    )  # 12.5% margin, within [0.075..., 0.175...]-ish range

    adjustment = compute_primary_adjustment(tested_party, rng)

    assert adjustment is None


def test_primary_adjustment_increases_income_when_below_range():
    df = _weighted_plis({"A": 0.10, "B": 0.12, "C": 0.14, "D": 0.16})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])
    tested_party = TestedParty(
        name="Below-range Co", fiscal_year=2025, revenue=1_000_000.0, operating_income=10_000.0
    )  # 1% margin, clearly below range

    adjustment = compute_primary_adjustment(tested_party, rng)

    assert adjustment is not None
    assert adjustment.direction == "increase"
    assert adjustment.target_margin == pytest.approx(rng.median)
    assert adjustment.target_operating_income == pytest.approx(
        rng.median * tested_party.revenue
    )
    assert adjustment.adjustment_amount == pytest.approx(
        adjustment.target_operating_income - tested_party.operating_income
    )
    assert adjustment.adjustment_amount > 0


def test_primary_adjustment_decreases_income_when_above_range():
    df = _weighted_plis({"A": 0.10, "B": 0.12, "C": 0.14, "D": 0.16})
    rng = compute_arms_length_range(df, "operating_margin", ["A", "B", "C", "D"])
    tested_party = TestedParty(
        name="Above-range Co", fiscal_year=2025, revenue=1_000_000.0, operating_income=500_000.0
    )  # 50% margin, clearly above range

    adjustment = compute_primary_adjustment(tested_party, rng)

    assert adjustment is not None
    assert adjustment.direction == "decrease"
    assert adjustment.adjustment_amount < 0


def test_tested_party_operating_margin_property():
    tested_party = TestedParty(
        name="X", fiscal_year=2025, revenue=200.0, operating_income=20.0
    )
    assert tested_party.operating_margin == pytest.approx(0.10)
