import csv
import os
from datetime import date, datetime, timedelta
from collections import defaultdict
from image_amounts import IMAGE_EVENT_AMOUNTS

# Resolve the dataset directory relative to this file by default, but allow an override
# via the BUY_OR_WAIT_DATASET environment variable (e.g. when the grader mounts the
# dataset somewhere else, or when running against a different copy of the data).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET = os.environ.get("BUY_OR_WAIT_DATASET", os.path.join(_THIS_DIR, "..", "dataset"))


def pdate(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_csv(name):
    with open(f"{DATASET}/{name}", newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_profiles():
    rows = load_csv("financial_profiles.csv")
    out = {}
    for r in rows:
        out[r["user_id"]] = {
            "user_id": r["user_id"],
            "home_currency": r["home_currency"],
            "current_available_balance": float(r["current_available_balance"]),
            "minimum_balance_to_keep": float(r["minimum_balance_to_keep"]),
            "financial_priorities": [x for x in r["financial_priorities"].split("|") if x],
            "protect": set(x for x in r["expense_categories_to_protect"].split("|") if x),
            "willing_reduce": set(x for x in r["expense_categories_user_is_willing_to_reduce"].split("|") if x),
            "willing_stop": set(x for x in r["expense_categories_user_is_willing_to_stop"].split("|") if x),
            "payment_methods": set(x for x in r["payment_methods_user_will_consider"].split("|") if x),
            "max_installment_months": int(r["max_installment_months"]) if r["max_installment_months"] else None,
        }
    return out


def load_exchange_rates():
    rows = load_csv("exchange_rates.csv")
    # rate[(date, from, to)] = rate
    rate = {}
    for r in rows:
        rate[(r["rate_date"], r["from_currency"], r["to_currency"])] = float(r["rate"])
    return rate


def convert(amount, from_ccy, to_ccy, on_date_str, rates):
    """Convert amount from from_ccy to to_ccy using the exact-date rate table.
    on_date_str: settlement date (YYYY-MM-DD) to look up.
    Falls back to identity if currencies match."""
    if from_ccy == to_ccy:
        return amount
    key = (on_date_str, from_ccy, to_ccy)
    if key in rates:
        return amount * rates[key]
    inv_key = (on_date_str, to_ccy, from_ccy)
    if inv_key in rates:
        return amount / rates[inv_key]
    # try nearest available date for that pair (fallback safety net; direct dataset
    # matches are exact on the 15th of each month in practice)
    candidates = [(d, f, t, v) for (d, f, t), v in rates.items() if f == from_ccy and t == to_ccy]
    if candidates:
        # nearest date
        target = pdate(on_date_str)
        best = min(candidates, key=lambda c: abs((pdate(c[0]) - target).days))
        return amount * best[3]
    candidates = [(d, f, t, v) for (d, f, t), v in rates.items() if f == to_ccy and t == from_ccy]
    if candidates:
        target = pdate(on_date_str)
        best = min(candidates, key=lambda c: abs((pdate(c[0]) - target).days))
        return amount / best[3]
    raise ValueError(f"No exchange rate found for {from_ccy}->{to_ccy} on {on_date_str}")


def load_events(rates, profiles):
    rows = load_csv("financial_events.csv")
    events = defaultdict(list)
    for r in rows:
        amt_raw = r["amount"]
        if amt_raw == "":
            amt = IMAGE_EVENT_AMOUNTS.get(r["event_id"])
            if amt is None:
                # No image found; cannot invent -- skip (should not happen in this dataset)
                continue
        else:
            amt = float(amt_raw)
        home_ccy = profiles[r["user_id"]]["home_currency"]
        ccy = r["currency"]
        settle = r["settlement_date"] or r["event_date"]
        amt_home = convert(amt, ccy, home_ccy, settle, rates) if ccy != home_ccy else amt
        events[r["user_id"]].append({
            "event_id": r["event_id"],
            "user_id": r["user_id"],
            "event_type": r["event_type"],
            "description": r["description"],
            "category": r["category"],
            "direction": r["direction"],
            "amount": amt,
            "amount_home": amt_home,
            "currency": ccy,
            "event_date": r["event_date"],
            "settlement_date": settle,
            "status": r["status"],
            "linked_event_id": r["linked_event_id"] or None,
            "flexibility": r["flexibility"],
            "minimum_allowed_amount": float(r["minimum_allowed_amount"]) if r["minimum_allowed_amount"] else None,
        })
    return events


def load_payment_options():
    rows = load_csv("request_payment_options.csv")
    out = defaultdict(list)
    for r in rows:
        out[r["request_id"]].append({
            "payment_option_id": r["payment_option_id"],
            "request_id": r["request_id"],
            "payment_method": r["payment_method"],
            "payment_amount": float(r["payment_amount"]),
            "number_of_payments": int(r["number_of_payments"]),
            "first_payment_date": r["first_payment_date"],
            "payment_frequency_days": int(r["payment_frequency_days"]) if r["payment_frequency_days"] else None,
            "financing_fee": float(r["financing_fee"]) if r["financing_fee"] else 0.0,
            "total_payable_amount": float(r["total_payable_amount"]),
        })
    for rid in out:
        out[rid].sort(key=lambda o: o["payment_option_id"])
    return out


def load_messages():
    rows = load_csv("messages.csv")
    by_user = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r)
    return by_user


def load_requests(fname="requests.csv"):
    rows = load_csv(fname)
    return rows
