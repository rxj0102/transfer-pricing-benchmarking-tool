"""Build a formatted Excel benchmarking report from the analysis outputs.

Transfer pricing context
-------------------------
A TNMM benchmarking study's deliverable is not just a final number -- it
is a set of exhibits a reviewing economist or tax authority can retrace:
which companies were considered, why each was kept or rejected, what
each comparable's multi-year PLI was, how the arm's length range was
built, and where the tested party landed. This module assembles exactly
those exhibits into a single Excel workbook, styled the way a report
attached to a real TP study typically looks (a title/disclaimer page
plus one clearly labeled worksheet per exhibit), from the outputs of
``screening.py``, ``pli_calculations.py``, ``benchmarking.py``, and
``cup.py``.

The workbook-construction logic (:func:`build_workbook`) is kept
separate from the file-writing step (:func:`write_report`) so it can be
unit tested without touching disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from tp_benchmarking.benchmarking import (
    ArmsLengthRange,
    PositioningResult,
    PrimaryAdjustment,
    TestedParty,
)
from tp_benchmarking.cup import LoanBenchmarkResult
from tp_benchmarking.screening import ScreeningResult

# ---------------------------------------------------------------------------
# Styling constants -- kept simple and consistent across every sheet.
# ---------------------------------------------------------------------------
_NAVY = "1F3864"
_LIGHT_BLUE = "D9E2F3"
_HIGHLIGHT = "FFF2CC"
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill("solid", fgColor=_NAVY)
_TITLE_FONT = Font(bold=True, size=16, color=_NAVY)
_SUBTITLE_FONT = Font(italic=True, size=10, color="595959")
_SECTION_FONT = Font(bold=True, size=12, color=_NAVY)
_THIN_BORDER = Border(*(Side(style="thin", color="BFBFBF") for _ in range(4)))
_PCT_FORMAT = "0.00%"
_USD_FORMAT = "#,##0"


@dataclass(frozen=True)
class TnmmReportInputs:
    """Everything the report needs from the TNMM (screening/PLI/range) side."""

    pli_name: str
    screening_result: ScreeningResult
    annual_plis: pd.DataFrame
    weighted_plis: pd.DataFrame
    arms_length_range: ArmsLengthRange
    tested_party: TestedParty
    positioning: PositioningResult
    primary_adjustment: PrimaryAdjustment | None


@dataclass(frozen=True)
class ReportInputs:
    """Full set of inputs for :func:`build_workbook`."""

    tnmm: TnmmReportInputs
    loan_benchmark: LoanBenchmarkResult
    as_of_date: date
    data_pull_date: date | None = None


def _write_header_row(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER


def _write_data_row(
    ws: Worksheet,
    row: int,
    values: list,
    *,
    formats: list[str | None] | None = None,
    highlight: bool = False,
) -> None:
    formats = formats or [None] * len(values)
    for col_idx, (value, fmt) in enumerate(zip(values, formats), start=1):
        cell = ws.cell(row=row, column=col_idx, value=value)
        cell.border = _THIN_BORDER
        if fmt:
            cell.number_format = fmt
        if highlight:
            cell.fill = PatternFill("solid", fgColor=_HIGHLIGHT)


def _autosize_columns(ws: Worksheet, widths: list[int]) -> None:
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def _add_title_block(ws: Worksheet, title: str, subtitle: str, start_row: int = 1) -> int:
    ws.cell(row=start_row, column=1, value=title).font = _TITLE_FONT
    ws.cell(row=start_row + 1, column=1, value=subtitle).font = _SUBTITLE_FONT
    return start_row + 3


def _build_cover_sheet(wb: Workbook, inputs: ReportInputs) -> None:
    ws = wb.active
    ws.title = "Cover & Summary"
    row = _add_title_block(
        ws,
        "Transfer Pricing Benchmarking Study",
        "Illustrative Transactional Net Margin Method (TNMM) Analysis "
        "+ Comparable Uncontrolled Price (CUP) Loan Benchmarking",
    )

    ws.cell(row=row, column=1, value=f"Report date: {inputs.as_of_date.isoformat()}")
    row += 1
    if inputs.data_pull_date:
        ws.cell(
            row=row,
            column=1,
            value=f"Comparable set financial data as of: {inputs.data_pull_date.isoformat()}",
        )
        row += 2
    else:
        row += 1

    ws.cell(row=row, column=1, value="DISCLAIMER").font = Font(bold=True, color="C00000")
    row += 1
    disclaimer = (
        "This report is an educational / methodology demonstration only. "
        "It is generated from free, public financial data (Yahoo Finance) "
        "as a substitute for licensed commercial comparables databases, "
        "uses a fictional hypothetical tested party and loan, and does not "
        "constitute a real economic analysis, a comparability study, or "
        "tax/legal advice under any jurisdiction's transfer pricing rules. "
        "See README.md for the full list of limitations."
    )
    ws.cell(row=row, column=1, value=disclaimer).alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.row_dimensions[row].height = 60
    row += 2

    tnmm = inputs.tnmm
    ws.cell(row=row, column=1, value="TNMM Summary").font = _SECTION_FONT
    row += 1
    summary_rows = [
        ("PLI tested", tnmm.pli_name.replace("_", " ").title()),
        ("Candidate comparables", len(tnmm.screening_result.company_log)),
        ("Comparables surviving all screens", len(tnmm.screening_result.final_comp_set)),
        (
            "Arm's length range (Q1 - Q3)",
            f"{tnmm.arms_length_range.q1:.2%} - {tnmm.arms_length_range.q3:.2%}",
        ),
        ("Median", f"{tnmm.arms_length_range.median:.2%}"),
        ("Tested party", tnmm.tested_party.name),
        ("Tested party result", f"{tnmm.positioning.pli_value:.2%}"),
        ("Position", tnmm.positioning.position.upper()),
    ]
    if tnmm.primary_adjustment:
        summary_rows.append(
            (
                "Primary adjustment",
                f"${tnmm.primary_adjustment.adjustment_amount:,.0f} "
                f"({tnmm.primary_adjustment.direction} to median)",
            )
        )
    else:
        summary_rows.append(("Primary adjustment", "None required (within range)"))

    for label, value in summary_rows:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    row += 1
    loan = inputs.loan_benchmark
    ws.cell(row=row, column=1, value="CUP Loan Benchmarking Summary").font = _SECTION_FONT
    row += 1
    loan_rows = [
        ("Loan principal", f"${loan.loan.principal:,.0f}"),
        ("Tenor / credit rating", f"{loan.loan.tenor} / {loan.loan.borrower_credit_rating}"),
        ("Benchmark rate (risk-free + spread)", f"{loan.benchmark_rate:.2%}"),
        ("Actual intercompany rate", f"{loan.loan.actual_annual_interest_rate:.2%}"),
        ("Difference", f"{loan.difference_bps:+.0f} bps"),
        ("Within tolerance", "Yes" if loan.within_tolerance else "No"),
    ]
    for label, value in loan_rows:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    _autosize_columns(ws, [38, 34, 14, 14, 14, 14])


def _build_screening_sheet(wb: Workbook, screening_result: ScreeningResult) -> None:
    ws = wb.create_sheet("Comp Set Screening Log")
    ws.cell(row=1, column=1, value="Comparable Search Screening Log").font = _TITLE_FONT
    ws.cell(
        row=2,
        column=1,
        value="Every candidate comparable, each screen's pass/fail result, and the reason.",
    ).font = _SUBTITLE_FONT

    headers = [
        "Ticker", "Company", "Industry", "Industry Screen",
        "Avg Revenue (USD)", "Revenue Screen", "Loss Years / Total",
        "Loss-Year Screen", "Related-Party Screen", "Included", "Exclusion Reason",
    ]
    header_row = 4
    _write_header_row(ws, header_row, headers)

    df = screening_result.company_log
    for i, (_, r) in enumerate(df.iterrows()):
        row = header_row + 1 + i
        values = [
            r["ticker"],
            r["company_name"],
            r["industry"],
            "PASS" if r["industry_screen_pass"] else "FAIL",
            r["avg_annual_revenue_usd"],
            "PASS" if r["revenue_screen_pass"] else "FAIL",
            f"{int(r['loss_years'])}/{int(r['total_years'])}",
            "PASS" if r["loss_year_screen_pass"] else "FAIL",
            r["related_party_screen_status"],
            "YES" if r["included"] else "NO",
            r["exclusion_reason"],
        ]
        formats = [None, None, None, None, _USD_FORMAT, None, None, None, None, None, None]
        _write_data_row(ws, row, values, formats=formats, highlight=not r["included"])

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    _autosize_columns(ws, [10, 26, 26, 14, 16, 14, 14, 14, 24, 10, 60])


def _build_pli_detail_sheet(wb: Workbook, annual_plis: pd.DataFrame) -> None:
    ws = wb.create_sheet("Annual PLI Detail")
    ws.cell(row=1, column=1, value="Comparable Set — Annual PLI Detail").font = _TITLE_FONT
    ws.cell(
        row=2, column=1,
        value="Per-year financials and PLIs for every candidate comparable "
              "(including years excluded from the multi-year average).",
    ).font = _SUBTITLE_FONT

    headers = [
        "Ticker", "Fiscal Year End", "Total Revenue", "Operating Income",
        "Gross Profit", "Operating Expense", "Cost of Revenue",
        "Operating Margin", "Berry Ratio", "Return on Total Costs",
        "Included in Avg?", "M&A Distortion Note",
    ]
    header_row = 4
    _write_header_row(ws, header_row, headers)

    df = annual_plis.sort_values(["ticker", "fiscal_year_end"])
    for i, (_, r) in enumerate(df.iterrows()):
        row = header_row + 1 + i
        values = [
            r["ticker"],
            str(r["fiscal_year_end"]),
            r["total_revenue"],
            r["operating_income"],
            r["gross_profit"],
            r["operating_expense"],
            r["cost_of_revenue"],
            r["operating_margin"],
            r["berry_ratio"],
            r["return_on_total_costs"],
            "Yes" if r["included_in_pli_average"] else "No",
            r["ma_distortion_note"],
        ]
        formats = [
            None, None, _USD_FORMAT, _USD_FORMAT, _USD_FORMAT, _USD_FORMAT, _USD_FORMAT,
            _PCT_FORMAT, "0.00", _PCT_FORMAT, None, None,
        ]
        _write_data_row(ws, row, values, formats=formats, highlight=not r["included_in_pli_average"])

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    _autosize_columns(ws, [10, 14, 16, 16, 16, 16, 16, 14, 12, 16, 14, 50])


def _build_range_sheet(wb: Workbook, tnmm: TnmmReportInputs) -> None:
    ws = wb.create_sheet("Arm's Length Range")
    ws.cell(row=1, column=1, value="Weighted-Average PLI & Arm's Length Range").font = _TITLE_FONT
    ws.cell(
        row=2, column=1,
        value=f"PLI: {tnmm.pli_name.replace('_', ' ').title()}  |  "
              f"Final comp set, n = {tnmm.arms_length_range.n_comparables}",
    ).font = _SUBTITLE_FONT

    headers = ["Ticker", tnmm.pli_name.replace("_", " ").title(), "Rank"]
    header_row = 4
    _write_header_row(ws, header_row, headers)

    for i, (ticker, value) in enumerate(tnmm.arms_length_range.values):
        row = header_row + 1 + i
        _write_data_row(ws, row, [ticker, value, i + 1], formats=[None, _PCT_FORMAT, None])

    stats_row = header_row + len(tnmm.arms_length_range.values) + 2
    rng = tnmm.arms_length_range
    stats = [
        ("25th percentile (Q1)", rng.q1),
        ("Median", rng.median),
        ("75th percentile (Q3)", rng.q3),
        ("Q1 (linear-interpolation method, for comparison)", rng.q1_interpolated),
        ("Q3 (linear-interpolation method, for comparison)", rng.q3_interpolated),
    ]
    for label, value in stats:
        ws.cell(row=stats_row, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=stats_row, column=2, value=value)
        cell.number_format = _PCT_FORMAT
        stats_row += 1

    stats_row += 1
    ws.cell(row=stats_row, column=1, value="Tested Party Positioning").font = _SECTION_FONT
    stats_row += 1
    tp = tnmm.tested_party
    positioning_rows = [
        ("Tested party", tp.name),
        ("Fiscal year", tp.fiscal_year),
        ("Revenue", tp.revenue),
        ("Operating income", tp.operating_income),
        ("Operating margin", tp.operating_margin),
        ("Position vs. range", tnmm.positioning.position.upper()),
    ]
    for label, value in positioning_rows:
        ws.cell(row=stats_row, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=stats_row, column=2, value=value)
        if label in ("Revenue", "Operating income"):
            cell.number_format = _USD_FORMAT
        elif label == "Operating margin":
            cell.number_format = _PCT_FORMAT
        stats_row += 1

    if tnmm.primary_adjustment:
        stats_row += 1
        ws.cell(row=stats_row, column=1, value="Primary Adjustment (to median)").font = _SECTION_FONT
        stats_row += 1
        adj = tnmm.primary_adjustment
        adjustment_rows = [
            ("Target margin (median)", adj.target_margin, _PCT_FORMAT),
            ("Target operating income", adj.target_operating_income, _USD_FORMAT),
            ("Adjustment amount", adj.adjustment_amount, _USD_FORMAT),
            ("Direction", adj.direction, None),
        ]
        for label, value, fmt in adjustment_rows:
            ws.cell(row=stats_row, column=1, value=label).font = Font(bold=True)
            cell = ws.cell(row=stats_row, column=2, value=value)
            if fmt:
                cell.number_format = fmt
            stats_row += 1

    _autosize_columns(ws, [40, 40, 10])


def _build_cup_sheet(wb: Workbook, loan_benchmark: LoanBenchmarkResult) -> None:
    ws = wb.create_sheet("CUP - Loan Benchmarking")
    ws.cell(row=1, column=1, value="CUP Module — Intercompany Loan Interest Rate").font = _TITLE_FONT
    ws.cell(
        row=2, column=1,
        value="Benchmark = matched-tenor public Treasury yield + illustrative credit spread.",
    ).font = _SUBTITLE_FONT

    loan = loan_benchmark.loan
    rows = [
        ("Loan principal", f"${loan.principal:,.0f}"),
        ("Tenor", loan.tenor),
        ("Borrower credit rating (assumed)", loan.borrower_credit_rating),
        ("Public risk-free rate (Treasury, live pull)", f"{loan_benchmark.risk_free_rate:.2%}"),
        ("Credit spread (illustrative table)", f"{loan_benchmark.credit_spread_bps:.0f} bps"),
        ("Benchmark rate", f"{loan_benchmark.benchmark_rate:.2%}"),
        ("Actual intercompany rate", f"{loan.actual_annual_interest_rate:.2%}"),
        ("Difference", f"{loan_benchmark.difference_bps:+.0f} bps"),
        ("Tolerance", f"±{loan_benchmark.tolerance_bps:.0f} bps"),
        ("Within tolerance", "Yes" if loan_benchmark.within_tolerance else "No"),
    ]
    row = 4
    for label, value in rows:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    _autosize_columns(ws, [42, 30])


def build_workbook(inputs: ReportInputs) -> Workbook:
    """Assemble the full benchmarking-report workbook in memory.

    Kept separate from disk I/O so the report's contents can be unit
    tested directly against an in-memory :class:`openpyxl.Workbook`.
    """
    wb = Workbook()
    _build_cover_sheet(wb, inputs)
    _build_screening_sheet(wb, inputs.tnmm.screening_result)
    _build_pli_detail_sheet(wb, inputs.tnmm.annual_plis)
    _build_range_sheet(wb, inputs.tnmm)
    _build_cup_sheet(wb, inputs.loan_benchmark)
    return wb


def write_report(inputs: ReportInputs, output_path: Path) -> Path:
    """Build and save the benchmarking report workbook to ``output_path``."""
    wb = build_workbook(inputs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
