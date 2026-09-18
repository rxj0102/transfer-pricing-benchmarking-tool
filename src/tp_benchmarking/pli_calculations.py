"""Profit Level Indicator (PLI) calculations.

Transfer pricing context
-------------------------
A Profit Level Indicator is the profitability ratio the TNMM compares
between the tested party and the comparable set. Which PLI is
appropriate depends on the tested party's functional profile -- this
tool computes all three of the PLIs most commonly used for a routine IT
/ business-process services provider, since in practice an economist
usually computes more than one PLI and checks that the conclusion is
robust across them, rather than picking one PLI in isolation:

- **Operating Margin** (Operating Income / Sales): the default PLI for a
  full-risk services provider whose revenue is the most reliable
  denominator -- appropriate when the tested party's value is driven by
  the scale of services delivered (headcount-billed IT services fit this
  well).
- **Berry Ratio** (Gross Profit / Operating Expenses): appropriate when
  the tested party's functions are closer to a distributor/agent whose
  compensation should track operating costs rather than revenue (e.g. a
  procurement or distribution entity where resale price varies with a
  pass-through cost of goods that says little about the entity's own
  value added). Included here for completeness/robustness-checking even
  though it is a somewhat unusual primary PLI for a pure IT services
  provider.
- **Return on Total Costs** (Operating Income / Total Costs, where Total
  Costs = Cost of Revenue + Operating Expense): common for contract
  manufacturers and cost-plus service providers, where cost is the best
  available proxy for the value/effort contributed.

Multiple-year weighted averaging
---------------------------------
Per OECD Guidelines para 3.57-3.62 and the worked examples in Treas. Reg.
§1.482-5(e), a single fiscal year's PLI can be distorted by short-term
noise (a large one-off contract, a bad quarter). The standard fix is to
use several years of data and aggregate them. This module aggregates by
**summing each year's numerator and denominator across the covered years,
then taking one ratio of the sums** -- not by averaging each year's
already-computed ratio. The two approaches usually land close together,
but summing first correctly gives more weight to a comparable's larger
fiscal years and avoids letting an unusually small year swing the average
PLI as much as a straight average-of-ratios would.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PLI_COLUMNS: list[str] = ["operating_margin", "berry_ratio", "return_on_total_costs"]


def compute_annual_plis(company_years: pd.DataFrame) -> pd.DataFrame:
    """Compute all three PLIs for each row (one company-fiscal-year).

    Parameters
    ----------
    company_years:
        Must contain ``total_revenue``, ``operating_income``,
        ``gross_profit``, ``operating_expense``, and ``cost_of_revenue``.

    Returns
    -------
    pandas.DataFrame
        A copy of the input with ``operating_margin``, ``berry_ratio``,
        and ``return_on_total_costs`` columns appended. A PLI is left as
        ``NaN`` for a row whose denominator is zero or negative (e.g. an
        operating-expense figure of zero would make the Berry Ratio
        undefined) rather than raising or silently returning ``inf`` --
        an undefined PLI is itself a data-quality fact worth surfacing.
    """
    df = company_years.copy()
    total_costs = df["cost_of_revenue"] + df["operating_expense"]

    df["operating_margin"] = _safe_ratio(df["operating_income"], df["total_revenue"])
    df["berry_ratio"] = _safe_ratio(df["gross_profit"], df["operating_expense"])
    df["return_on_total_costs"] = _safe_ratio(df["operating_income"], total_costs)
    return df


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Elementwise numerator/denominator, NaN wherever denominator <= 0."""
    denominator_valid = denominator.where(denominator > 0)
    return numerator / denominator_valid


def compute_weighted_average_plis(
    annual_plis: pd.DataFrame,
    *,
    only_included_years: bool = True,
) -> pd.DataFrame:
    """Aggregate per-year PLIs into one multi-year weighted-average PLI
    per comparable.

    Parameters
    ----------
    annual_plis:
        Output of :func:`compute_annual_plis`. If it has an
        ``included_in_pli_average`` boolean column (set by
        ``screening.py`` to flag M&A-distorted years), those years are
        excluded from the aggregation by default.
    only_included_years:
        Set to ``False`` to aggregate over every available fiscal year
        regardless of the M&A-distortion flag (mainly useful for
        sensitivity checks).

    Returns
    -------
    pandas.DataFrame
        One row per ticker: the number of fiscal years the average is
        based on (``years_used``) and the three weighted-average PLIs.
        A comparable with zero usable years (all its data excluded, or a
        PLI whose denominator was unusable in every year) gets ``NaN``
        for that PLI rather than being dropped, so the gap stays visible
        rather than silently disappearing from the comp set.
    """
    df = annual_plis.copy()
    if only_included_years and "included_in_pli_average" in df.columns:
        df = df[df["included_in_pli_average"]]

    total_costs = df["cost_of_revenue"] + df["operating_expense"]
    df = df.assign(_total_costs=total_costs)

    def aggregate(group: pd.DataFrame) -> pd.Series:
        opex_sum = group["operating_expense"].where(
            group["operating_expense"] > 0
        ).sum()
        revenue_sum = group["total_revenue"].where(group["total_revenue"] > 0).sum()
        cost_sum = group["_total_costs"].where(group["_total_costs"] > 0).sum()

        return pd.Series(
            {
                "years_used": len(group),
                "operating_margin": (
                    group["operating_income"].sum() / revenue_sum
                    if revenue_sum > 0
                    else np.nan
                ),
                "berry_ratio": (
                    group["gross_profit"].sum() / opex_sum if opex_sum > 0 else np.nan
                ),
                "return_on_total_costs": (
                    group["operating_income"].sum() / cost_sum
                    if cost_sum > 0
                    else np.nan
                ),
            }
        )

    result = df.groupby("ticker", as_index=False).apply(
        aggregate, include_groups=False
    )
    return result.reset_index(drop=True)
