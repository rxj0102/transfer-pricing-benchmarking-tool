"""Arm's length range construction and tested-party benchmarking.

Transfer pricing context
-------------------------
Once a final comparable set's weighted-average PLIs are computed, the
TNMM analysis asks two questions:

1. What is the **arm's length range**? Treas. Reg. §1.482-1(e)(2)(iii)
   allows use of the full range of comparable results only when the
   comparables are so alike that any differences would not materially
   affect the PLI; in practice they almost never are, so U.S. practice
   (and the OECD Guidelines, para 3.57, similarly) instead uses the
   **interquartile range** -- the middle 50% of comparable results -- to
   dampen the effect of any residual, unquantifiable comparability
   defects at the tails of the distribution.

2. Does the **tested party** (the controlled entity whose result is
   actually being tested -- typically the less complex party to the
   transaction) fall inside that range? If not, Treas. Reg.
   §1.482-1(e)(3) allows a **primary adjustment**, and the regulation's
   own convention (absent a showing that some other point in the range
   is more reliable) is to adjust the tested party's result to the
   range's **median**, not merely to the nearest edge of the range.

A note on the interquartile-range calculation itself
------------------------------------------------------
There are two methods in common use, and they can give slightly
different numbers on the same data:

- The **linear-interpolation** method (what Excel's ``PERCENTILE.INC``
  and NumPy's default ``np.percentile`` compute): treats percentiles as
  points that may fall *between* two observed values, interpolating
  linearly.
- The **regulatory / nearest-rank** method described in Treas. Reg.
  §1.482-1(e)(2)(iii): for a given percentile, take the smallest
  observed result such that at least that percentage of all results are
  at or below it (with the two middle values averaged in the case of an
  exact split). This method's quartile boundaries, unlike the
  interpolation method's, are always an actual observed result (or the
  average of two adjacent ones) rather than an interpolated value.

This module implements **both** and treats the regulatory method as the
default/primary one, since it is what a U.S. transfer pricing analysis
would actually rely on -- the interpolation method is provided alongside
it for comparison, because the two are easy to conflate and a reviewer
familiar with Excel's QUARTILE function should be able to see exactly
where the two diverge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ArmsLengthRange:
    """The arm's length range derived from the final comparable set.

    Attributes
    ----------
    pli_name:
        Which PLI this range was built from (e.g. ``"operating_margin"``).
    q1, median, q3:
        25th/50th/75th percentile of the comparable set's weighted-average
        PLI, computed using the Treas. Reg. §1.482-1(e)(2)(iii) rank-based
        method (see module docstring).
    q1_interpolated, q3_interpolated:
        The same two boundaries computed instead via linear interpolation
        (NumPy/Excel convention), included for comparison.
    n_comparables:
        Number of comparables the range is based on.
    values:
        The sorted, underlying comparable PLI values (ticker, value) used
        to build the range -- kept for the report/notebook to show its work.
    """

    pli_name: str
    q1: float
    median: float
    q3: float
    q1_interpolated: float
    q3_interpolated: float
    n_comparables: int
    values: list[tuple[str, float]]


@dataclass(frozen=True)
class TestedParty:
    """A hypothetical tested party for illustrating the benchmarking step.

    This is a fictional entity, not a real company, invented solely to
    demonstrate how a tested party's result is compared against an arm's
    length range and how a primary adjustment would be computed. See
    ``README.md`` for the disclaimer that this entire project is a
    methodology demonstration, not a real economic analysis.
    """

    __test__ = False  # tell pytest this isn't a test class despite the name

    name: str
    fiscal_year: int
    revenue: float
    operating_income: float

    @property
    def operating_margin(self) -> float:
        return self.operating_income / self.revenue


# A hypothetical wholly-owned offshore IT service delivery subsidiary of a
# US parent -- e.g. a captive entity providing application development and
# maintenance services back to its parent on a cost-plus-like basis. The
# revenue and operating income are invented for illustration; they are
# deliberately set low enough that the resulting ~5.5% operating margin
# falls below the comparable set's interquartile range, so the primary
# adjustment mechanic in this module has something real to compute.
HYPOTHETICAL_TESTED_PARTY = TestedParty(
    name="TestCo Services Ltd. (hypothetical)",
    fiscal_year=2025,
    revenue=80_000_000.0,
    operating_income=4_400_000.0,
)


def _rank_percentile(sorted_values: list[float], percentile: float) -> float:
    """Treas. Reg. §1.482-1(e)(2)(iii)-style rank-based percentile.

    Parameters
    ----------
    sorted_values:
        Values already sorted ascending.
    percentile:
        Fraction in (0, 1], e.g. ``0.25`` for the 25th percentile.
    """
    n = len(sorted_values)
    position = percentile * n
    if math.isclose(position, round(position)):
        k = round(position)
        if k == 0:
            return sorted_values[0]
        if k >= n:
            return sorted_values[-1]
        # Exact split: average the two values on either side of the cut.
        return (sorted_values[k - 1] + sorted_values[k]) / 2
    k = math.ceil(position)
    return sorted_values[min(k, n) - 1]


def compute_arms_length_range(
    weighted_plis: pd.DataFrame,
    pli_name: str,
    final_comp_set: list[str],
) -> ArmsLengthRange:
    """Build the arm's length range for one PLI from the final comp set.

    Parameters
    ----------
    weighted_plis:
        Output of :func:`pli_calculations.compute_weighted_average_plis`
        (one row per ticker).
    pli_name:
        Which PLI column to build the range from, e.g.
        ``"operating_margin"``, ``"berry_ratio"``, or
        ``"return_on_total_costs"``.
    final_comp_set:
        Tickers that survived the comparability screens (see
        ``screening.ScreeningResult.final_comp_set``) -- only these
        contribute to the range.

    Returns
    -------
    ArmsLengthRange

    Raises
    ------
    ValueError
        If fewer than 3 comparables have a usable (non-NaN) value for
        this PLI. Three is an absolute floor for a quartile calculation
        to mean anything at all; in practice most real studies would
        want considerably more before relying on the result.
    """
    subset = weighted_plis[weighted_plis["ticker"].isin(final_comp_set)]
    subset = subset.dropna(subset=[pli_name])
    if len(subset) < 3:
        raise ValueError(
            f"Only {len(subset)} comparable(s) have a usable {pli_name} "
            "value; at least 3 are required to compute a meaningful "
            "interquartile range."
        )

    pairs = sorted(zip(subset["ticker"], subset[pli_name]), key=lambda p: p[1])
    values = [v for _, v in pairs]

    q1_interp, q3_interp = np.percentile(values, [25, 75])

    return ArmsLengthRange(
        pli_name=pli_name,
        q1=_rank_percentile(values, 0.25),
        median=_rank_percentile(values, 0.50),
        q3=_rank_percentile(values, 0.75),
        q1_interpolated=float(q1_interp),
        q3_interpolated=float(q3_interp),
        n_comparables=len(values),
        values=pairs,
    )


@dataclass(frozen=True)
class PositioningResult:
    """Where a tested party's result falls relative to the arm's length range."""

    pli_value: float
    arms_length_range: ArmsLengthRange
    in_range: bool
    position: str  # "below range", "within range", or "above range"


def assess_position(pli_value: float, arms_length_range: ArmsLengthRange) -> PositioningResult:
    """Determine whether a tested party's PLI falls within the arm's length range."""
    if pli_value < arms_length_range.q1:
        position = "below range"
    elif pli_value > arms_length_range.q3:
        position = "above range"
    else:
        position = "within range"
    return PositioningResult(
        pli_value=pli_value,
        arms_length_range=arms_length_range,
        in_range=(position == "within range"),
        position=position,
    )


@dataclass(frozen=True)
class PrimaryAdjustment:
    """A primary adjustment bringing a tested party's result to the range median.

    Modeled on Treas. Reg. §1.482-1(e)(3): where a controlled taxpayer's
    reported result falls outside the arm's length range, the result may
    be adjusted to the median of the range (absent a showing that some
    other point in the range better reflects the controlled transaction's
    facts).
    """

    tested_party: TestedParty
    target_margin: float
    target_operating_income: float
    adjustment_amount: float
    direction: str  # "increase" or "decrease"


def compute_primary_adjustment(
    tested_party: TestedParty, arms_length_range: ArmsLengthRange
) -> PrimaryAdjustment | None:
    """Compute the primary adjustment needed to bring a tested party to
    the arm's length range's median, if its result falls outside the range.

    Returns
    -------
    PrimaryAdjustment | None
        ``None`` if the tested party's PLI is already within the range
        (no adjustment is warranted). Otherwise, the adjustment that
        would move the tested party's *operating income* (holding
        revenue fixed) to the level implied by the range median.

    Notes
    -----
    This function assumes the PLI in question is ``operating_margin``
    (Operating Income / Sales), since that is the PLI for which "target
    operating income at the median" has a direct, single-line-item
    meaning. Applying the same mechanic to the Berry Ratio or Return on
    Total Costs would instead solve for a target gross profit or a
    target cost base -- left out here since the hypothetical tested
    party in this project is framed as a routine services provider best
    tested on Operating Margin.
    """
    position = assess_position(tested_party.operating_margin, arms_length_range)
    if position.in_range:
        return None

    target_margin = arms_length_range.median
    target_operating_income = target_margin * tested_party.revenue
    adjustment_amount = target_operating_income - tested_party.operating_income
    direction = "increase" if adjustment_amount > 0 else "decrease"

    return PrimaryAdjustment(
        tested_party=tested_party,
        target_margin=target_margin,
        target_operating_income=target_operating_income,
        adjustment_amount=adjustment_amount,
        direction=direction,
    )
