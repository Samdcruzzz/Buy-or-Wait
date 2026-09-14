from datetime import timedelta
from loaders import pdate

WINDOW_DAYS = 90


def build_daily_balance(current_balance, forecast_events, request_date_s, window_days=WINDOW_DAYS):
    """Returns dict date_str -> balance at END of that day (after all that day's events),
    for every day from request_date to request_date+window_days inclusive.
    forecast_events: list of {date, amount_home} (signed: credit +, debit -)."""
    req = pdate(request_date_s)
    end = req + timedelta(days=window_days)
    by_date = {}
    for ev in forecast_events:
        by_date.setdefault(ev["date"], 0.0)
        by_date[ev["date"]] += ev["amount_home"]

    balances = {}
    bal = current_balance
    d = req
    while d <= end:
        ds = d.isoformat()
        bal += by_date.get(ds, 0.0)
        balances[ds] = bal
        d += timedelta(days=1)
    return balances


def cushion_series(balances, min_balance):
    return {d: b - min_balance for d, b in balances.items()}


def suffix_min(cushion, dates_sorted):
    """Return dict date -> min(cushion[d:]) i.e. minimum cushion from that date to the end."""
    out = {}
    running = float("inf")
    for d in reversed(dates_sorted):
        running = min(running, cushion[d])
        out[d] = running
    return out


def amount_safe_to_pay(current_balance, forecast_events, request_date_s, min_balance, requested_amount, window_days=WINDOW_DAYS):
    balances = build_daily_balance(current_balance, forecast_events, request_date_s, window_days)
    cushion = cushion_series(balances, min_balance)
    dates_sorted = sorted(cushion.keys())
    min_cushion_whole_window = min(cushion[d] for d in dates_sorted)
    safe = max(0.0, min(requested_amount, min_cushion_whole_window))
    return safe, balances, cushion, dates_sorted


def earliest_full_payment_date(current_balance, forecast_events, request_date_s, min_balance, requested_amount, window_days=WINDOW_DAYS):
    balances = build_daily_balance(current_balance, forecast_events, request_date_s, window_days)
    cushion = cushion_series(balances, min_balance)
    dates_sorted = sorted(cushion.keys())
    smin = suffix_min(cushion, dates_sorted)
    for d in dates_sorted:
        if smin[d] >= requested_amount - 1e-9:
            return d
    return None
