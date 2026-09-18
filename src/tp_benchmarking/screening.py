"""Comparability screens applied to the candidate comparable set.

Transfer pricing context
-------------------------
Under the OECD Transfer Pricing Guidelines (Chapter III) and U.S. Treas.
Reg. §1.482-5, a comparable company search is not "pull a list of
same-industry tickers and average their margins." It is a documented,
defensible narrowing process: start from a broad candidate set, apply a
series of quantitative and qualitative screens, and -- critically --
**keep a record of every exclusion and why**, so a tax authority or
reviewing economist can retrace the logic. That retained record is
usually called the comparable search's "screening log" or "rejection
matrix." ``run_comparability_screens`` below produces exactly that: a
company-level table with a pass/fail flag and a reason for every screen,
not just a final yes/no.

The five screens implemented here mirror the ones most real TNMM studies
apply first, in the order a reviewer would expect to see them:

1. **Industry/functional classification** (proxy for a SIC/NAICS code
   match) -- is this company plausibly performing the same functions as
   the tested party?
2. **Minimum revenue threshold** -- is the company a going concern of
   comparable scale, not a shell or micro-cap whose margins are noisy for
   reasons unrelated to its business model?
3. **Persistent operating losses** -- a company that consistently loses
   money is presumptively not operating on arm's length terms itself
   (nobody would agree, at arm's length, to provide services at a
   sustained loss), so it is excluded as a comparable regardless of why
   it is unprofitable.
4. **Significant related-party revenue** -- a comparable's own margin is
   only informative if it was earned dealing with *independent*
   customers/suppliers. Public U.S. issuers must disclose related-party
   *transactions* under ASC 850 but are not required to disclose
   related-party revenue as a *percentage of total revenue* at the
   granularity a TP screen needs. That data is simply not available from
   the sources this project uses. Rather than silently ignore the issue,
   this screen is implemented as an explicit "cannot be evaluated, flagged
   as a limitation" step -- see ``RELATED_PARTY_SCREEN_NOTE``.
5. **M&A-distorted years** -- an acquisition or divestiture can produce a
   one-time step-change in revenue or margin that has nothing to do with
   the ongoing business's arm's length profitability. Rather than drop
   the whole company, this screen excludes only the distorted fiscal
   year(s) from that company's weighted-average PLI.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# ---------------------------------------------------------------------------
# Screen 1: industry / functional classification
# ---------------------------------------------------------------------------
TARGET_INDUSTRY = "Information Technology Services"

# Yahoo Finance's industry taxonomy is a data-vendor convenience label, not
# a SIC/NAICS filing. It occasionally misclassifies a company relative to
# its actual filed business description. A real comparability search
# handles this with a manual functional review step after the automated
# screen -- this dict is that manual step, made explicit and auditable
# rather than silently overriding the automated result.
#
# Endava plc (DAVA) is tagged "Software - Infrastructure" by Yahoo, but
# Endava's own 20-F describes it as a payments/technology *services*
# provider delivering custom software engineering and IT consulting to
# enterprise clients on a time-and-materials / fixed-fee basis --
# functionally indistinguishable from the other comparables in this set.
# It is added back based on that functional review.
MANUAL_INDUSTRY_OVERRIDES: dict[str, str] = {
    "DAVA": (
        "Data vendor classifies as 'Software - Infrastructure', but "
        "Endava's public filings describe an IT/software engineering "
        "services business functionally comparable to the rest of this "
        "set. Included based on manual functional review, consistent "
        "with standard comparable-search practice of following an "
        "automated code screen with a qualitative check."
    )
}

# ---------------------------------------------------------------------------
# Screen 2: minimum revenue threshold
# ---------------------------------------------------------------------------
# A conservative floor meant to exclude shell companies / micro-caps whose
# reported margins are dominated by fixed-cost noise rather than a
# representative business model. Applied to each comparable's average
# USD-equivalent revenue across its available fiscal years (see
# data_pull.get_fx_rate_to_usd for the non-USD reporters).
MIN_AVERAGE_ANNUAL_REVENUE_USD = 50_000_000.0

# ---------------------------------------------------------------------------
# Screen 3: persistent operating losses
# ---------------------------------------------------------------------------
# A comparable is excluded if it reported an operating loss in *more than
# half* of its available (non-M&A-distorted) fiscal years. This is
# deliberately a majority test, not "any loss year," per the OECD
# Guidelines' own framing (para 3.64): an isolated loss year does not by
# itself disqualify a comparable, but a persistent pattern of losses
# suggests the company is not operating on arm's length terms.
LOSS_YEAR_MAJORITY_THRESHOLD = 0.5

# ---------------------------------------------------------------------------
# Screen 4: related-party revenue
# ---------------------------------------------------------------------------
RELATED_PARTY_SCREEN_NOTE = (
    "Not evaluated: related-party revenue as a % of total revenue is not "
    "disclosed in public financial-statement data (10-K/20-F ASC 850 "
    "disclosures cover related-party transactions, not their share of "
    "total revenue at the granularity needed for this screen). A "
    "commercial TP database (e.g. Bureau van Dijk/Moody's Orbis) or "
    "direct review of each comparable's related-party footnote would be "
    "required to apply this screen properly. Documented here as a "
    "limitation of this tool rather than silently skipped."
)

# ---------------------------------------------------------------------------
# Screen 5: M&A-distorted years
# ---------------------------------------------------------------------------
# A single fiscal year is flagged (and excluded from that comparable's
# weighted-average PLI -- the rest of the company's years are unaffected)
# if year-over-year revenue growth exceeds this threshold in either
# direction. +/-30% is a deliberately wide band: normal organic growth or
# contraction in this industry (see the double-digit YoY swings some of
# these comps post organically) should not trip it, so a year that does
# trip it is a real outlier worth a closer look, not routine noise.
MA_DISTORTION_YOY_THRESHOLD = 0.30


@dataclass(frozen=True)
class ScreeningResult:
    """Output of :func:`run_comparability_screens`.

    Attributes
    ----------
    company_year_log:
        One row per (ticker, fiscal_year_end) with the M&A-distortion flag
        and whether that specific year is included in the weighted-average
        PLI computation.
    company_log:
        One row per candidate ticker: pass/fail + reason for every
        company-level screen, and the final ``included`` decision. This is
        the "screening log" exhibit for the benchmarking report.
    final_comp_set:
        Tickers of comparables that survived every screen.
    """

    company_year_log: pd.DataFrame
    company_log: pd.DataFrame
    final_comp_set: list[str]


def _apply_industry_screen(profiles: pd.DataFrame) -> pd.DataFrame:
    def screen_one(row: pd.Series) -> tuple[bool, str]:
        if row["industry"] == TARGET_INDUSTRY:
            return True, f"Industry match: '{TARGET_INDUSTRY}'"
        override_reason = MANUAL_INDUSTRY_OVERRIDES.get(row["ticker"])
        if override_reason:
            return True, override_reason
        return False, (
            f"Industry '{row['industry']}' does not match target "
            f"'{TARGET_INDUSTRY}' and no manual override is documented."
        )

    results = profiles.apply(screen_one, axis=1, result_type="expand")
    profiles = profiles.copy()
    profiles["industry_screen_pass"] = results[0]
    profiles["industry_screen_note"] = results[1]
    return profiles


def _flag_ma_distorted_years(company_years: pd.DataFrame) -> pd.DataFrame:
    df = company_years.sort_values(["ticker", "fiscal_year_end"]).copy()
    df["yoy_revenue_growth"] = df.groupby("ticker")["total_revenue"].pct_change()

    def flag_one(growth: float) -> tuple[bool, str]:
        if pd.isna(growth):
            return False, "First available fiscal year for this comparable; no prior-year growth rate to test."
        if abs(growth) > MA_DISTORTION_YOY_THRESHOLD:
            direction = "increase" if growth > 0 else "decrease"
            return True, (
                f"YoY revenue {direction} of {growth:.1%} exceeds the "
                f"{MA_DISTORTION_YOY_THRESHOLD:.0%} threshold; excluded from "
                f"this comparable's weighted-average PLI as a possible "
                f"M&A-distorted year."
            )
        return False, f"YoY revenue change of {growth:.1%} is within the {MA_DISTORTION_YOY_THRESHOLD:.0%} threshold."

    flags = df["yoy_revenue_growth"].apply(flag_one)
    df["ma_distortion_flag"] = flags.apply(lambda t: t[0])
    df["ma_distortion_note"] = flags.apply(lambda t: t[1])
    df["included_in_pli_average"] = ~df["ma_distortion_flag"]
    return df


def _apply_revenue_screen(
    company_years: pd.DataFrame, profiles: pd.DataFrame
) -> pd.DataFrame:
    avg_revenue = (
        company_years[company_years["included_in_pli_average"]]
        .groupby("ticker")["total_revenue_usd"]
        .mean()
        .rename("avg_annual_revenue_usd")
    )
    profiles = profiles.merge(avg_revenue, on="ticker", how="left")
    profiles["revenue_screen_pass"] = (
        profiles["avg_annual_revenue_usd"] >= MIN_AVERAGE_ANNUAL_REVENUE_USD
    )
    profiles["revenue_screen_note"] = profiles.apply(
        lambda r: (
            f"Average annual revenue of ${r['avg_annual_revenue_usd']:,.0f} "
            f"{'meets' if r['revenue_screen_pass'] else 'is below'} the "
            f"${MIN_AVERAGE_ANNUAL_REVENUE_USD:,.0f} minimum."
        ),
        axis=1,
    )
    return profiles


def _apply_loss_year_screen(
    company_years: pd.DataFrame, profiles: pd.DataFrame
) -> pd.DataFrame:
    evaluable = company_years[company_years["included_in_pli_average"]].copy()
    evaluable["is_loss_year"] = evaluable["operating_income"] < 0

    summary = evaluable.groupby("ticker").agg(
        loss_years=("is_loss_year", "sum"),
        total_years=("is_loss_year", "count"),
    )
    summary["loss_year_fraction"] = summary["loss_years"] / summary["total_years"]
    summary["loss_year_screen_pass"] = (
        summary["loss_year_fraction"] <= LOSS_YEAR_MAJORITY_THRESHOLD
    )
    summary["loss_year_screen_note"] = summary.apply(
        lambda r: (
            f"Operating loss in {int(r['loss_years'])} of "
            f"{int(r['total_years'])} evaluated fiscal years "
            f"({r['loss_year_fraction']:.0%}); "
            + (
                "does not exceed"
                if r["loss_year_screen_pass"]
                else "exceeds"
            )
            + f" the {LOSS_YEAR_MAJORITY_THRESHOLD:.0%} persistent-loss threshold."
        ),
        axis=1,
    )
    profiles = profiles.merge(
        summary[
            ["loss_years", "total_years", "loss_year_fraction",
             "loss_year_screen_pass", "loss_year_screen_note"]
        ],
        on="ticker",
        how="left",
    )
    return profiles


def run_comparability_screens(raw_comp_set: pd.DataFrame) -> ScreeningResult:
    """Apply all five comparability screens to the candidate comp set.

    Parameters
    ----------
    raw_comp_set:
        The tidy long-format table from
        :func:`tp_benchmarking.data_pull.pull_comp_set` (one row per
        ticker x fiscal year, with profile columns joined in).

    Returns
    -------
    ScreeningResult
        Company-year log (M&A-distortion flags), company-level screening
        log (pass/fail + reason per screen), and the final surviving
        ticker list.
    """
    company_years = _flag_ma_distorted_years(raw_comp_set)

    profile_cols = [
        "ticker",
        "company_name",
        "sector",
        "industry",
        "financial_currency",
    ]
    profiles = raw_comp_set[profile_cols].drop_duplicates("ticker").reset_index(
        drop=True
    )

    profiles = _apply_industry_screen(profiles)
    profiles = _apply_revenue_screen(company_years, profiles)
    profiles = _apply_loss_year_screen(company_years, profiles)
    profiles["related_party_screen_status"] = "Not evaluated (see note)"
    profiles["related_party_screen_note"] = RELATED_PARTY_SCREEN_NOTE

    profiles["included"] = (
        profiles["industry_screen_pass"]
        & profiles["revenue_screen_pass"]
        & profiles["loss_year_screen_pass"]
        # Related-party screen cannot fail a comparable -- it is a
        # disclosed limitation, not a pass/fail gate, given the data is
        # unavailable rather than unfavorable.
    )
    profiles["exclusion_reason"] = profiles.apply(_summarize_exclusion, axis=1)

    final_comp_set = profiles.loc[profiles["included"], "ticker"].tolist()

    return ScreeningResult(
        company_year_log=company_years,
        company_log=profiles,
        final_comp_set=final_comp_set,
    )


def _summarize_exclusion(row: pd.Series) -> str:
    if row["included"]:
        return ""
    reasons = []
    if not row["industry_screen_pass"]:
        reasons.append(row["industry_screen_note"])
    if not row["revenue_screen_pass"]:
        reasons.append(row["revenue_screen_note"])
    if not row["loss_year_screen_pass"]:
        reasons.append(row["loss_year_screen_note"])
    return " | ".join(reasons)
