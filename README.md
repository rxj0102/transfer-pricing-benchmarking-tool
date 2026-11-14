# Transfer Pricing Benchmarking Tool

[![CI](https://github.com/rxj0102/transfer-pricing-benchmarking-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/rxj0102/transfer-pricing-benchmarking-tool/actions/workflows/ci.yml)

A comparable-company benchmarking tool that replicates the core mechanics of a
**Transactional Net Margin Method (TNMM)** study under the OECD Transfer
Pricing Guidelines and U.S. Treas. Reg. §1.482-5, built entirely on free,
public data.

> **This is an educational / methodology demonstration project**, not a real
> economic analysis, comparability study, or tax/legal advice. See
> [Disclaimer & Limitations](#disclaimer--limitations) before relying on
> anything in this repository for any purpose beyond illustration. It was
> built as a portfolio project to demonstrate transfer pricing methodology
> alongside software engineering practice.

## What is transfer pricing?

When two entities under common ownership (e.g. a parent company and its
foreign subsidiary) transact with each other — one entity providing services,
licensing IP, lending money, or selling goods to the other — tax authorities
require that transaction to be priced as if the two entities were unrelated,
independent parties. This is the **arm's length principle**, and the practice
of setting and defending those intercompany prices is **transfer pricing**.
Because these transactions cross tax jurisdictions, mispricing them (even
unintentionally) can shift taxable profit between countries, which is why
transfer pricing is one of the most heavily scrutinized areas of international
tax.

## What is TNMM?

The **Transactional Net Margin Method** is the most commonly used transfer
pricing method for routine transactions (services, distribution, contract
manufacturing). Rather than comparing prices line by line, it compares a
**net profit margin** — a "Profit Level Indicator" (PLI) — earned by the
tested party (the controlled entity being examined) to the margins earned by
**independent companies performing similar functions** (the "comparable
set"). If the tested party's margin falls within the range of outcomes the
comparables produced, its result is considered consistent with the arm's
length standard; if not, a **primary adjustment** may bring it into line.

## What this tool automates

This project builds a full TNMM comparable-search-and-benchmarking pipeline
against a real (free) data source, end to end:

| Step | Module | What it does |
|---|---|---|
| 1. Data sourcing | `data_pull.py` | Pulls annual income-statement data and company profiles for a candidate set of IT/BPO services companies via `yfinance`, with currency-aware handling for non-USD reporters |
| 2. Comparability screens | `screening.py` | Applies five standard screens — industry/functional match, minimum revenue, persistent operating losses, related-party revenue (flagged as unavailable), and M&A-distorted years — producing an auditable screening log |
| 3. PLI calculation | `pli_calculations.py` | Computes Operating Margin, Berry Ratio, and Return on Total Costs per comparable per year, and multi-year weighted averages |
| 4. Arm's length range | `benchmarking.py` | Builds the interquartile range from the final comparable set (implementing both the Treas. Reg. §1.482-1(e)(2)(iii) rank-based method and the linear-interpolation method, for comparison), positions a hypothetical tested party against it, and computes a primary adjustment to the median where the result falls outside the range |
| 5. CUP module | `cup.py` | A second, simpler method: benchmarks a hypothetical intercompany loan's interest rate against a public Treasury yield + credit-spread CUP |
| 6. Reporting | `report.py` | Assembles every exhibit above into a styled, multi-sheet Excel workbook |

A full walkthrough with commentary explaining each step in transfer pricing
terms — not just code — is in
[`notebooks/tnmm_benchmarking_walkthrough.ipynb`](notebooks/tnmm_benchmarking_walkthrough.ipynb).

### The comparable set

Ten independent, publicly listed IT/business-process outsourcing services
companies (EPAM, Globant, Endava, Grid Dynamics, Genpact, ExlService,
Cognizant, Infosys, Wipro, DXC), deliberately excluding diversified mega-caps
(e.g. Accenture) and companies no longer independently public (WNS, acquired
by Capgemini in 2025). Grid Dynamics is excluded by the screening logic itself
(persistent operating losses); the other nine survive to the final comp set.
A **dated data snapshot is committed** in `data/` so the analysis is
reproducible without a live pull — see [Refreshing the data](#refreshing-the-data)
to pull current figures instead.

## Repository layout

```
transfer-pricing-benchmarking-tool/
├── src/tp_benchmarking/
│   ├── data_pull.py          # Pull comparable-set financials via yfinance
│   ├── screening.py          # Comparability screens + auditable screening log
│   ├── pli_calculations.py   # PLI math + multi-year weighted averages
│   ├── benchmarking.py       # Arm's length range, tested-party positioning, primary adjustment
│   ├── cup.py                # CUP loan interest rate benchmarking
│   └── report.py             # Excel benchmarking report generator
├── notebooks/
│   └── tnmm_benchmarking_walkthrough.ipynb   # Full end-to-end walkthrough with TP commentary
├── data/                      # Committed, dated data snapshot (+ pull metadata)
├── output/                    # Generated Excel report lands here (gitignored)
├── tests/                     # pytest unit tests for every module
├── requirements.txt
├── pyproject.toml
└── LICENSE
```

## How to run it

### 1. Install

```bash
git clone https://github.com/rxj0102/transfer-pricing-benchmarking-tool.git
cd transfer-pricing-benchmarking-tool
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
pip install -e .
```

### 2. Run the notebook

```bash
jupyter notebook notebooks/tnmm_benchmarking_walkthrough.ipynb
```

This runs the full pipeline against the committed data snapshot (no network
access required) and regenerates `output/tp_benchmarking_report.xlsx`. The
notebook is also committed **with its outputs**, so it renders results
directly on GitHub without needing to run it.

### 3. Generate the report from the command line

```python
from datetime import date
from pathlib import Path
from tp_benchmarking.data_pull import pull_comp_set, get_pull_date
from tp_benchmarking.screening import run_comparability_screens
from tp_benchmarking.pli_calculations import compute_annual_plis, compute_weighted_average_plis
from tp_benchmarking.benchmarking import (
    compute_arms_length_range, assess_position, compute_primary_adjustment,
    HYPOTHETICAL_TESTED_PARTY,
)
from tp_benchmarking.cup import benchmark_loan_interest_rate, HYPOTHETICAL_INTERCOMPANY_LOAN
from tp_benchmarking.report import ReportInputs, TnmmReportInputs, write_report

raw = pull_comp_set()
screening = run_comparability_screens(raw)
annual = compute_annual_plis(screening.company_year_log)
weighted = compute_weighted_average_plis(annual)
rng = compute_arms_length_range(weighted, "operating_margin", screening.final_comp_set)
tp = HYPOTHETICAL_TESTED_PARTY
positioning = assess_position(tp.operating_margin, rng)
adjustment = compute_primary_adjustment(tp, rng)
loan_result = benchmark_loan_interest_rate(HYPOTHETICAL_INTERCOMPANY_LOAN)

write_report(
    ReportInputs(
        tnmm=TnmmReportInputs("operating_margin", screening, annual, weighted, rng, tp, positioning, adjustment),
        loan_benchmark=loan_result,
        as_of_date=date.today(),
        data_pull_date=get_pull_date(),
    ),
    Path("output/tp_benchmarking_report.xlsx"),
)
```

### 4. Run the tests

```bash
pytest
```

45+ unit tests cover the screening logic, PLI math (including the
sum-then-ratio weighted-average convention), the interquartile range
calculation (including a case where the regulatory and interpolation methods
provably diverge), and the report structure — all against synthetic data, so
they run without network access. One or two tests per data-touching module
are marked to hit the live network as a smoke test; set
`TP_BENCHMARKING_SKIP_NETWORK_TESTS=1` to skip them in an offline environment.

### Refreshing the data

```python
from tp_benchmarking.data_pull import pull_comp_set
pull_comp_set(use_cache=False)  # overwrites the committed data/ snapshot with a live pull
```

## Methodology notes worth reading before you judge the numbers

- **PLIs are currency-invariant; the revenue screen isn't.** Wipro reports in
  INR and Endava in GBP; everyone else reports in USD. Since every PLI here is
  a ratio of two line items from the same company's own statement, currency
  never distorts the PLI itself — but the revenue-floor screen compares
  absolute figures across companies, so it uses a spot FX conversion
  (see `data_pull.get_fx_rate_to_usd`), itself a simplification versus a real
  study's period-matched average rates.
- **Regulatory vs. interpolated interquartile range.** Treas. Reg.
  §1.482-1(e)(2)(iii) defines the interquartile range with a rank-based method
  that differs from the linear-interpolation method Excel's `PERCENTILE.INC`
  and NumPy's `np.percentile` use by default. Both are implemented in
  `benchmarking.py`, with the regulatory method treated as primary — they
  happen to coincide exactly on the current 9-comparable data pull (a property
  of that sample size, not of the methods being equivalent in general; see
  `tests/test_benchmarking.py::test_regulatory_and_interpolated_methods_can_diverge`
  for a case where they don't).
- **Multi-year averaging sums first, then divides.** The weighted-average PLI
  sums each comparable's numerator and denominator across its covered years
  before taking one ratio — not an average of each year's already-computed
  ratio — per the convention in Treas. Reg. §1.482-5(e)'s worked examples.
- **The related-party revenue screen cannot be evaluated.** Public
  10-K/20-F filings disclose related-party *transactions* under ASC 850, not
  related-party revenue as a share of total revenue at the granularity a real
  screen needs. Rather than skip this silently, `screening.py` flags it
  explicitly as a limitation on every comparable.

## Disclaimer & Limitations

**This repository is an educational and methodology-demonstration project.
It is not a real economic analysis, a comparability study, or tax or legal
advice, and must not be relied on as a substitute for one.** Specific,
non-exhaustive limitations:

- **Data source**: financial data comes from Yahoo Finance via `yfinance`, a
  free, retail-investor-oriented feed — not a licensed commercial comparables
  database (S&P Capital IQ, Moody's Orbis/Bureau van Dijk, RoyaltyStat).
  Figures have not been independently verified against each company's actual
  filed financial statements.
- **Related-party revenue** cannot be screened from public data (see above) —
  a real comparable search requires this and this tool cannot provide it.
- **Candidate comparable set** was assembled from public industry knowledge,
  not a queried SIC/NAICS database, and is not represented as exhaustive.
- **FX conversion** for the revenue screen uses a single static spot rate,
  not period-matched average rates.
- **The CUP module's credit spread table is static and illustrative**, not a
  live market data feed.
- **The tested party and intercompany loan are entirely fictional**, invented
  to illustrate the benchmarking mechanics — they do not represent any real
  taxpayer's facts, functions, or risks.
- **No functional or risk analysis** is performed. A real TNMM study begins
  with a detailed functional analysis of both the tested party and every
  comparable; this tool starts from the assumption that the comparables'
  functional profiles are already known to be reasonably similar.

## Reproducibility

### Data availability

All inputs come from free, public sources. No paid data or API keys are required unless noted.

- Yahoo Finance via the yfinance package (free, no key)
- SEC EDGAR filings (free, requires a User-Agent header)
- Files shipped in the `data/` folder of this repository

### Computational requirements

- Python 3.12.3. Every dependency version is pinned in `uv.lock`.
- Checked on Linux x86_64 with 2 CPU cores and 8 GB RAM. No GPU is needed.

```bash
pip install uv     # once
uv sync            # installs the exact pinned environment
uv run pytest -q   # runs the test suite
```

### Runtime

The test suite (51 tests) finishes in about 12 seconds on the machine above, including any data downloads it triggers.

### Citation

Citation metadata is in `CITATION.cff`. GitHub turns it into a Cite this repository button on the repo page.


## License

MIT — see [LICENSE](LICENSE).
