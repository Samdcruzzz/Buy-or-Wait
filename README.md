# Buy or Wait? — Deterministic Financial Affordability Engine

A rule-based decision engine that answers a deceptively simple question — **"Can I afford this?"** — by reconstructing a user's full financial state from messy, multi-currency, multi-source data and simulating 90 days forward before recommending how (and when) to pay.

Built for the HackerRank *Orchestrate* challenge (Sep 2026).

## What it does

Given a user's request (e.g. "Can I afford this laptop?"), the engine:

1. **Reconstructs financial state** — merges historical/pending transactions, recurring income and expenses, non-cash investments, and confirmed future salary across five currencies (INR, ZAR, IDR, USD, EUR), converting via dated exchange rates.
2. **Resolves ambiguity from unstructured data** — extracts missing transaction amounts from receipt/payslip/invoice images, and classifies free-text messages (English + Indonesian) to detect cancellations, delays, confirmations, and amendments that override the raw transaction log.
3. **Forecasts 90 days of daily balance** — simulating recurring income/expenses and confirmed payments to find the largest amount safely payable today and the earliest date the full amount becomes safe, without ever breaching the user's minimum balance.
4. **Generates a ranked, rule-compliant recommendation** — evaluating every eligible payment method (full payment, partial payment, installments, wait, not recommended) against a strict six-level tie-break hierarchy, and produces a grounded, human-readable explanation for each decision.

## Why deterministic Python, not an LLM call

No live LLM API key was available in the build environment. Rather than fake or stub model calls, the engine was built as a fully deterministic, auditable Python pipeline — every recurring-cadence detection, currency conversion, forecast, and tie-break rule is reproducible and traceable to the spec. Message and image interpretation (extracting amounts from receipts, classifying ~40 semantic message templates) was done once during development and encoded as rules, rather than metered per-request. This trades some flexibility for full reproducibility, zero inference cost, and 100% scoring-relevant transparency — every number in `output.csv` can be traced back to a specific line of code and a specific input row.

## Architecture

```
code/
├── main.py                  # Pipeline entrypoint
├── loaders.py                # CSV loading + exact-date currency conversion
├── reconstruct.py             # Recurring income/expense detection, salary state machine
├── forecast.py                 # 90-day daily balance simulation, safety checks
├── decide.py                    # Candidate payment-plan enumeration + ranking
├── decision_pipeline.py           # Explanation generation, orchestration
├── formatting.py                    # Output formatting to spec
├── message_rules.py                   # Deterministic message classifier
├── image_amounts.py                     # Extracted image-derived amounts
├── requirements.txt
├── README.md
└── evaluation/
    ├── validate_samples.py                # Scoring against sample_requests.csv
    └── usage_report.md                      # Token/cost accounting
```

### Key engineering decisions

- **Majority-rhythm cadence detection**: a gap-tolerant cadence estimator that folds whole-multiple gaps (e.g. a skipped month) back to the base rhythm, instead of letting a plain median get corrupted by one irregular interval.
- **Sequential salary state machine**: tracks employment changes, terminal payroll markers, and unconfirmed/pending gig income as explicit stop signals rather than blending them into the recurring-income baseline.
- **Scale-invariant regularity guard**: a coefficient-of-variation check applied uniformly regardless of how many historical occurrences exist, to decide whether a category is "recurring" at all.
- **Six-level plan ranking**: deadline completion → no spending changes → minimize total paid → earliest start → fewest payments → lowest `payment_option_id`, applied mechanically to every candidate plan.

## Validation & results

- Validated iteratively against the 25 labeled `sample_requests.csv` rows, closing three genuine reconstruction bugs (terminal-payroll detection, pending-gig-income handling, blended-cadence desync) rather than tuning constants to fit.
- Final full run: **250/250 requests processed, zero errors, zero constraint violations** (`0 ≤ amount_safe_to_pay ≤ requested_amount` holds on every row).
- Output distribution: 60 `affordable_now` · 58 `affordable_with_plan` · 53 `affordable_later` · 79 `not_affordable`.
- Fully reproducible: a clean extraction of `code.zip` regenerates `output.csv` byte-for-byte.

## Known limitations

Documented honestly in `code/README.md`: some `amount_safe_to_pay` values retain a calibration gap against the hidden reference on a handful of users where essential-expense estimation (e.g. average vs. peak of recent variable spend) is under-constrained by the 25 available samples. Several alternative approaches were tested and reverted after confirming net regressions, in favor of generalizing rather than overfitting to known examples.

## Running it

```bash
cd code
pip install -r requirements.txt
python main.py --requests dataset/requests.csv --output output.csv
python evaluation/validate_samples.py   # score against sample_requests.csv
```

## Stack

Python · pandas · deterministic rule-based classification · multi-currency time-series forecasting — no external API dependency in the scored run.
