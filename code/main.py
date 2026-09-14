#!/usr/bin/env python3
"""
Buy or Wait? -- affordability decision engine.

Usage:
    python3 main.py [--requests requests.csv] [--out output.csv]

By default this reads dataset/requests.csv (relative to this file's parent directory,
i.e. ../dataset/requests.csv) and writes output.csv into the current working directory.
Set BUY_OR_WAIT_DATASET to point at a different dataset/ folder if needed.

The pipeline is fully deterministic (no live LLM calls at run time):
  1. loaders.py         -- CSV loading + exact-date currency conversion
  2. image_amounts.py   -- amounts for the 16 blank-amount events, extracted once by
                            direct (human/AI) inspection of dataset/media/images/*.png
  3. message_rules.py   -- rule-based classifier for the ~40 recurring message templates
                            used across messages.csv (English + Indonesian)
  4. reconstruct.py      -- recurring-expense/income detection + message-driven overrides,
                            producing a 90-day forward event forecast per user
  5. forecast.py         -- daily balance simulation, amount_safe_to_pay and
                            earliest_date_for_full_payment
  6. decide.py /
     decision_pipeline.py -- candidate payment-plan enumeration, ranking, spending-change
                            search, and decision_explanation generation
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loaders import (load_profiles, load_exchange_rates, load_events, load_messages,
                      load_requests, load_payment_options, convert)
from reconstruct import build_forecast_events
from decision_pipeline import decide_request
from formatting import fmt_amount

OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
]


def run(requests_filename="requests.csv", out_path="output.csv"):
    profiles = load_profiles()
    rates = load_exchange_rates()
    events = load_events(rates, profiles)
    messages = load_messages()
    payment_options = load_payment_options()
    requests_rows = load_requests(requests_filename)

    def rates_convert(amt, from_ccy, to_ccy, on_date):
        return convert(amt, from_ccy, to_ccy, on_date, rates)

    rows_out = []
    for r in requests_rows:
        uid = r["user_id"]
        profile = profiles[uid]
        user_events = events.get(uid, [])
        forecast_events = build_forecast_events(
            uid, profile, user_events, messages, rates_convert, r["request_date"])
        popts = payment_options.get(r["request_id"], [])
        result = decide_request(r, profile, forecast_events, user_events, popts)
        result["amount_safe_to_pay"] = fmt_amount(result["amount_safe_to_pay"]).replace(",", "")
        rows_out.append({c: result[c] for c in OUTPUT_COLUMNS})

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows to {out_path}")
    return rows_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Buy or Wait? affordability engine")
    parser.add_argument("--requests", default="requests.csv",
                         help="Requests CSV filename inside dataset/ (default: requests.csv)")
    parser.add_argument("--out", default="output.csv", help="Output CSV path")
    args = parser.parse_args()
    run(args.requests, args.out)
