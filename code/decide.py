import itertools
from datetime import timedelta
from loaders import pdate
from forecast import build_daily_balance, cushion_series, amount_safe_to_pay, earliest_full_payment_date, WINDOW_DAYS


def whole_window_min_cushion(current_balance, forecast_events, request_date_s, min_balance):
    balances = build_daily_balance(current_balance, forecast_events, request_date_s)
    cushion = cushion_series(balances, min_balance)
    return min(cushion.values())


def flexible_change_candidates(profile, forecast_events):
    """Return list of (category, action, target_amount_or_None, ref_event_id) for categories
    the user is willing to stop/reduce AND that actually appear as recurring flexible items
    in the forecast (so we only ever touch things that really recur for this user)."""
    out = []
    cats_in_forecast = {}
    for ev in forecast_events:
        if ev["kind"] == "recurring" and ev["amount_home"] < 0:
            cats_in_forecast.setdefault(ev["category"], []).append(ev)
    for cat in sorted(profile["willing_stop"]):
        if cat in cats_in_forecast:
            out.append((cat, "stop", None))
    for cat in sorted(profile["willing_reduce"]):
        if cat in cats_in_forecast:
            out.append((cat, "reduce", None))
    return out, cats_in_forecast


def apply_change(forecast_events, category, action, min_allowed_amount):
    out = []
    for ev in forecast_events:
        if ev["kind"] == "recurring" and ev["category"] == category and ev["amount_home"] < 0:
            if action == "stop":
                continue  # drop entirely
            elif action == "reduce":
                cap = -min_allowed_amount if min_allowed_amount is not None else 0
                out.append({**ev, "amount_home": max(ev["amount_home"], cap)})
                continue
        out.append(ev)
    return out


def find_min_allowed(events_all, category, request_date_s):
    vals = [e["minimum_allowed_amount"] for e in events_all
             if e["category"] == category and e["minimum_allowed_amount"] is not None
             and e["event_date"] <= request_date_s]
    if vals:
        return vals[-1]
    return 0


def find_ref_event_id(events_all, category, request_date_s):
    hist = [e for e in events_all if e["category"] == category and e["event_date"] <= request_date_s
            and e["status"] == "settled"]
    hist.sort(key=lambda e: e["event_date"])
    return hist[-1]["event_id"] if hist else None


def best_change_combo_for_full_today(profile, forecast_events, events_all, request_date_s,
                                       current_balance, min_balance, requested_amount, max_changes=3):
    """Search increasing-size combos of permitted stop/reduce changes to find the smallest
    set that makes the FULL requested amount safe to pay on request_date. Returns
    (list_of_(category,action,ref_event_id,target_amount), resulting_forecast_events) or (None, None)."""
    candidates, cats_in_forecast = flexible_change_candidates(profile, forecast_events)
    if not candidates:
        return None, None
    for size in range(1, min(max_changes, len(candidates)) + 1):
        for combo in itertools.combinations(candidates, size):
            # mutual exclusivity: never both stop and reduce the same category (can't happen here
            # since each category appears at most once across willing_stop/willing_reduce by construction)
            fe = forecast_events
            details = []
            for cat, action, _ in combo:
                min_allowed = find_min_allowed(events_all, cat, request_date_s)
                fe = apply_change(fe, cat, action, min_allowed)
                ref_id = find_ref_event_id(events_all, cat, request_date_s)
                details.append((cat, action, ref_id, min_allowed))
            min_cushion = whole_window_min_cushion(current_balance, fe, request_date_s, min_balance)
            if min_cushion >= requested_amount - 1e-9:
                return details, fe
    return None, None


def build_installment_candidates(payment_options, profile, forecast_events, request_date_s,
                                   current_balance, min_balance, desired_completion_s):
    out = []
    for opt in payment_options:
        if opt["payment_method"] != "installments":
            continue
        if "installments" not in profile["payment_methods"]:
            continue
        dates = []
        d = pdate(opt["first_payment_date"])
        for i in range(opt["number_of_payments"]):
            dates.append((d + timedelta(days=(opt["payment_frequency_days"] or 30) * i)).isoformat())
        extra_events = [{"date": dd, "amount_home": -opt["payment_amount"], "kind": "plan_payment"} for dd in dates]
        fe = forecast_events + extra_events
        min_cushion = whole_window_min_cushion(current_balance, fe, request_date_s, min_balance)
        safe = min_cushion >= -1e-6
        last_date = dates[-1]
        completes_on_time = last_date <= desired_completion_s
        out.append({
            "safe": safe,
            "completes_on_time": completes_on_time,
            "option": opt,
            "dates": dates,
            "total_paid": opt["total_payable_amount"],
            "first_payment_date": dates[0],
            "num_payments": opt["number_of_payments"],
            "payment_option_id": opt["payment_option_id"],
        })
    return out
