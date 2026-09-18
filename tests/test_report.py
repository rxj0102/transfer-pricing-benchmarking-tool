"""Tests for tp_benchmarking.report, using small synthetic inputs so the
report structure can be checked without a live data pull."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tp_benchmarking.benchmarking import (
    TestedParty,
    assess_position,
    compute_arms_length_range,
    compute_primary_adjustment,
)
from tp_benchmarking.cup import IntercompanyLoan, benchmark_loan_interest_rate
from tp_benchmarking.pli_calculations import (
    compute_annual_plis,
    compute_weighted_average_plis,
)
from tp_benchmarking.report import (
    ReportInputs,
    TnmmReportInputs,
    build_workbook,
    write_report,
)
from tp_benchmarking.screening import run_comparability_screens


def _synthetic_screening_result():
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    rows = []
    for t, base_margin in zip(tickers, [0.10, 0.12, 0.14, 0.16]):
        for year in range(2022, 2026):
            revenue = 100_000_000.0
            op_income = revenue * base_margin
            rows.append(
                {
                    "ticker": t,
                    "fiscal_year_end": pd.Timestamp(f"{year}-12-31"),
                    "total_revenue": revenue,
                    "operating_income": op_income,
                    "gross_profit": revenue * 0.3,
                    "operating_expense": revenue * 0.15,
                    "cost_of_revenue": revenue * 0.7,
                    "company_name": f"{t} Corp",
                    "sector": "Technology",
                    "industry": "Information Technology Services",
                    "financial_currency": "USD",
                    "fx_rate_to_usd": 1.0,
                    "total_revenue_usd": revenue,
                }
            )
    return run_comparability_screens(pd.DataFrame(rows))


@pytest.fixture
def report_inputs() -> ReportInputs:
    screening = _synthetic_screening_result()
    annual = compute_annual_plis(screening.company_year_log)
    weighted = compute_weighted_average_plis(annual)
    rng = compute_arms_length_range(
        weighted, "operating_margin", screening.final_comp_set
    )
    tested_party = TestedParty(
        name="Synthetic TestCo",
        fiscal_year=2025,
        revenue=50_000_000.0,
        operating_income=2_000_000.0,  # 4% margin, below range
    )
    positioning = assess_position(tested_party.operating_margin, rng)
    adjustment = compute_primary_adjustment(tested_party, rng)

    loan = IntercompanyLoan(
        principal=5_000_000.0,
        tenor="5-year",
        borrower_credit_rating="BBB",
        actual_annual_interest_rate=0.03,
    )
    loan_result = benchmark_loan_interest_rate(loan, risk_free_rate=0.045)

    tnmm = TnmmReportInputs(
        pli_name="operating_margin",
        screening_result=screening,
        annual_plis=annual,
        weighted_plis=weighted,
        arms_length_range=rng,
        tested_party=tested_party,
        positioning=positioning,
        primary_adjustment=adjustment,
    )
    return ReportInputs(
        tnmm=tnmm,
        loan_benchmark=loan_result,
        as_of_date=date(2026, 1, 1),
        data_pull_date=date(2025, 12, 31),
    )


def test_build_workbook_creates_expected_sheets(report_inputs):
    wb = build_workbook(report_inputs)

    assert wb.sheetnames == [
        "Cover & Summary",
        "Comp Set Screening Log",
        "Annual PLI Detail",
        "Arm's Length Range",
        "CUP - Loan Benchmarking",
    ]


def test_screening_sheet_lists_every_candidate(report_inputs):
    wb = build_workbook(report_inputs)
    ws = wb["Comp Set Screening Log"]

    header_row = 4
    tickers_in_sheet = {
        ws.cell(row=r, column=1).value
        for r in range(header_row + 1, ws.max_row + 1)
    }
    expected_tickers = set(report_inputs.tnmm.screening_result.company_log["ticker"])
    assert tickers_in_sheet == expected_tickers


def test_range_sheet_contains_quartile_values(report_inputs):
    wb = build_workbook(report_inputs)
    ws = wb["Arm's Length Range"]

    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "Median" in labels
    assert "25th percentile (Q1)" in labels
    assert "75th percentile (Q3)" in labels
    assert "Tested Party Positioning" in labels
    assert "Primary Adjustment (to median)" in labels  # tested party is below range


def test_cover_sheet_includes_disclaimer(report_inputs):
    wb = build_workbook(report_inputs)
    ws = wb["Cover & Summary"]

    all_text = " ".join(
        str(cell.value)
        for row in ws.iter_rows()
        for cell in row
        if cell.value is not None
    )
    assert "educational" in all_text.lower()
    assert "not constitute" in all_text.lower()


def test_cup_sheet_reports_loan_terms(report_inputs):
    wb = build_workbook(report_inputs)
    ws = wb["CUP - Loan Benchmarking"]

    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "Actual intercompany rate" in labels
    assert "Benchmark rate" in labels


def test_write_report_saves_a_readable_xlsx_file(report_inputs, tmp_path):
    output_path = tmp_path / "report.xlsx"

    result_path = write_report(report_inputs, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    from openpyxl import load_workbook

    wb = load_workbook(output_path)
    assert "Cover & Summary" in wb.sheetnames
