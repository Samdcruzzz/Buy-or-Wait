from datetime import timedelta
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from loaders import pdate
from message_rules import classify, extract_all_amounts, extract_all_dates, extract_pct

RECURRING_MIN_OCCURRENCES = 3
WINDOW_DAYS = 90

NON_RECURRING_CATEGORIES = {"investment", "windfall", "work_expense"}


def step_date(d, cadence_days):
    """Advance date d by one occurrence. If the detected cadence looks monthly (~1 calendar
    month), step by a true calendar month (preserves day-of-month, handles Jan31->Feb28 etc.)
    instead of a fixed day-count, since day-count stepping drifts against real monthly billing
    cycles over a 90-day / 3-cycle window. Otherwise step by the exact day-count cadence
    (used for multi-times-a-month variable essentials like groceries/transport/dining)."""
    if 25 <= cadence_days <= 35:
        return d + relativedelta(months=+1)
    return d + timedelta(days=cadence_days)


def settled_history(events, request_date_s):
    return [e for e in events if e["status"] == "settled" and e["event_date"] <= request_date_s]


def median(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return v[mid]
    return (v[mid - 1] + v[mid]) / 2.0


def detect_cadence(dates_sorted):
    """dates_sorted: list of date objects, ascending. Returns the underlying interval in days,
    or None.

    Gap-tolerant: a single skipped cycle (e.g. an unpaid-leave month, a missed weekly gig
    payout) produces a diff that is a whole multiple of the true cadence, not evidence of a
    slower or less-regular cadence. A plain median/mean over raw diffs lets one such gap
    silently distort the detected cadence (e.g. two monthly diffs of 31 and 91 days average to
    61, which is neither a real monthly nor bimonthly cadence and desyncs every projected
    occurrence after it). Conversely, a minority of short irregular gaps (e.g. a one-off
    arrears follow-up payment shortly after a job change) shouldn't be allowed to drag the
    cadence down either.

    We find the "majority rhythm" -- the diff value with the most other diffs directly close
    to it (tight tolerance, no multiplication) -- then fold any diff that looks like a whole
    multiple of that rhythm (a missed cycle) back down, leaving genuine short irregularities
    untouched, and take the median of the result.
    """
    if len(dates_sorted) < 2:
        return None
    diffs = [(dates_sorted[i + 1] - dates_sorted[i]).days for i in range(len(dates_sorted) - 1)]
    if len(diffs) == 1:
        return diffs[0]
    best_base = None
    best_count = -1
    for candidate in diffs:
        if candidate <= 0:
            continue
        tol = max(3, candidate * 0.15)
        count = sum(1 for d in diffs if abs(d - candidate) <= tol)
        if count > best_count or (count == best_count and (best_base is None or candidate < best_base)):
            best_count = count
            best_base = candidate
    if best_base is None:
        return median(diffs)
    normalized = []
    for d in diffs:
        if d > best_base * 1.5:
            k = round(d / best_base)
            normalized.append(d / k if k >= 2 else d)
        else:
            normalized.append(d)
    return median(normalized)


import re

GIG_CADENCE_THRESHOLD_DAYS = 25  # below this, salary arrives more than ~monthly -> treat as
                                  # unconfirmed/irregular gig income, not a projectable recurring wage
FINAL_PAYROLL_RE = re.compile(r'\bfinal\b|\blast\s+(pay|payroll|salary)\b|severance', re.I)


def build_salary_state(user_id, all_events, messages_by_user, request_date_s):
    """Sequential state machine over salary-related messages -> forecast rule for 'salary' category."""
    req_date = pdate(request_date_s)
    hist = [e for e in settled_history(all_events, request_date_s) if e["category"] == "salary" and e["direction"] == "credit"]
    hist.sort(key=lambda e: e["event_date"])
    hist_dates = [pdate(e["event_date"]) for e in hist]
    raw_cadence = detect_cadence(hist_dates)
    cadence = round(raw_cadence) if raw_cadence else 30

    state = {
        "amount": hist[-1]["amount_home"] if hist else None,
        "anchor_date": hist_dates[-1] if hist_dates else None,
        "stopped": False,
        "one_time_extras": [],  # list of (amount_home, date)
        "next_override": None,  # amount to use for the single next occurrence
    }

    # NOTE: a cadence-based "gig income" cutoff was tried here and reverted -- it incorrectly
    # flagged legitimate multi-stream income (base salary + commission, two household incomes)
    # as unprojectable, because combining all "salary"-category rows before measuring cadence
    # blends multiple real, independently-monthly streams into a false high-frequency signal.
    # A reliable per-stream split would need more than description-keyword heuristics, so for
    # now we only act on the unambiguous terminal-marker signal below.

    # An explicit terminal marker on the most recent settled salary ("Final employer payroll",
    # "Last payroll", a severance description, etc.) means no further salary is expected.
    if hist and FINAL_PAYROLL_RE.search(hist[-1]["description"] or ""):
        state["stopped"] = True

    # Also capture an explicit 'scheduled' next-confirmed-salary row (financial_events.csv),
    # which -- when present -- is authoritative for the *next* occurrence's date/amount, and
    # becomes the new baseline for every occurrence after it (a raise/new confirmed rate),
    # not just a single one-off credit.
    scheduled_next = [e for e in all_events if e["category"] == "salary" and e["direction"] == "credit"
                       and e["status"] == "scheduled"]
    scheduled_next.sort(key=lambda e: e["event_date"])
    if scheduled_next:
        s0 = scheduled_next[0]
        s0_date = pdate(s0["event_date"])
        if state["stopped"]:
            # Salary looked stopped/irregular from history alone, but this one occurrence is
            # explicitly confirmed -- count just that one credit, without resuming an ongoing
            # monthly projection we have no real evidence for.
            state["one_time_extras"].append((s0["amount_home"], s0_date.isoformat()))
        elif state["anchor_date"] is None or s0_date > state["anchor_date"]:
            state["amount"] = s0["amount_home"]
            state["anchor_date"] = s0_date
            if cadence < GIG_CADENCE_THRESHOLD_DAYS:
                # The blended settled history looked more-than-monthly-frequent (a classic
                # symptom of two concurrent income streams -- e.g. a base salary plus a
                # commission line, or two household incomes -- being blended together before
                # cadence was measured). The scheduled 'next confirmed salary' row is a single,
                # explicit payroll figure, so step forward on a normal monthly cadence rather
                # than the misleading blended one.
                cadence = 30

    msgs = [m for m in messages_by_user.get(user_id, [])]
    msgs.sort(key=lambda m: m["sent_at"])

    for m in msgs:
        action, text = classify(m["message_text"])
        amounts = extract_all_amounts(text)
        dates = extract_all_dates(text)
        if action == "NEW_JOB_FIRST_SALARY" and amounts:
            state["amount"] = amounts[0][1]
            state["anchor_date"] = pdate(dates[0]) if dates else state["anchor_date"]
            state["stopped"] = False
        elif action == "BASE_SALARY_CONFIRMED" and amounts:
            state["amount"] = amounts[0][1]
        elif action in ("EMPLOYMENT_ENDED", "SEASONAL_ENDED", "GIG_INCOME_UNCERTAIN"):
            state["stopped"] = True
        elif action == "RESUME_WITH_NEW_EXPENSE" and amounts:
            state["amount"] = amounts[0][1]
            state["anchor_date"] = pdate(dates[0]) if dates else state["anchor_date"]
            state["stopped"] = False
        elif action == "PERMANENT_INCREASE" and amounts:
            state["amount"] = amounts[0][1]
            if dates:
                state["anchor_date"] = pdate(dates[0])
        elif action == "ONE_SOURCE_ENDED_REMAINING" and amounts:
            state["amount"] = amounts[0][1]
        elif action == "DATE_CHANGE" and dates:
            state["anchor_date"] = pdate(dates[0])
        elif action == "LEAVE_REDUCED_NEXT" and amounts:
            state["next_override"] = amounts[0][1]
        elif action == "TEMP_REDUCED_NEXT" and amounts:
            state["next_override"] = amounts[0][1]
        elif action == "ARREARS_ONE_TIME" and len(amounts) >= 2:
            state["amount"] = amounts[0][1]
            state["_pending_extra"] = amounts[1][1]
        # NOOP / SCAM / others: no state change

    return state, cadence, scheduled_next


def project_salary(state, cadence, scheduled_next, request_date_s, window_end_s):
    """Generate list of (date_str, amount) salary credits within [request_date, window_end]."""
    req = pdate(request_date_s)
    end = pdate(window_end_s)
    out = []

    # One-time confirmed credits apply regardless of whether ongoing projection is stopped.
    for amt, d in state.get("one_time_extras", []):
        if request_date_s <= d <= window_end_s:
            out.append((d, amt))

    if state["stopped"] or state["amount"] is None:
        return out

    anchor = state["anchor_date"]
    amount = state["amount"]

    # Determine next occurrence date >= request_date
    if anchor is None:
        return out
    nxt = anchor
    while nxt < req:
        nxt = step_date(nxt, cadence)

    first = True
    while nxt <= end:
        amt = amount
        if first and state.get("next_override") is not None:
            amt = state["next_override"]
        out.append((nxt.isoformat(), amt))
        first = False
        nxt = step_date(nxt, cadence)

    extra = state.get("_pending_extra")
    if extra and out:
        # attach arrears to the first occurrence date within window
        out.append((out[0][0], extra))

    return out


def detect_generic_recurring(events, category, direction, request_date_s):
    hist = [e for e in settled_history(events, request_date_s) if e["category"] == category and e["direction"] == direction]
    hist.sort(key=lambda e: e["event_date"])
    if len(hist) < RECURRING_MIN_OCCURRENCES:
        return None
    dates = [pdate(e["event_date"]) for e in hist]
    diffs = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    cadence = detect_cadence(dates)
    if cadence is None or cadence <= 0:
        return None
    # Regularity guard: reject as "recurring" if intervals are wildly inconsistent even after
    # folding whole-cycle gaps (a leave month, a missed weekly payout) back into the base
    # cadence. Uses a scale-invariant coefficient of variation on the gap-normalized diffs, so
    # it applies uniformly regardless of how many settled occurrences exist -- a handful of
    # genuinely one-off events shouldn't be promoted to "recurring" just because there happen
    # to be >= 3 of them.
    normalized = []
    for d in diffs:
        if d > cadence * 1.5:
            k = round(d / cadence)
            normalized.append(d / k if k >= 2 else d)
        else:
            normalized.append(d)
    mean_norm = sum(normalized) / len(normalized)
    if mean_norm > 0:
        variance = sum((x - mean_norm) ** 2 for x in normalized) / len(normalized)
        cv = (variance ** 0.5) / mean_norm
        if cv > 0.4:
            return None
    amounts = [e["amount_home"] for e in hist]
    return {
        "last_date": dates[-1],
        "cadence": round(cadence),
        "avg_amount": sum(amounts) / len(amounts),
        "max_amount": max(amounts),
        "last_amount": amounts[-1],
        "recent_avg": sum(amounts[-6:]) / len(amounts[-6:]),
        "sample_event": hist[-1],
    }


VARIABLE_ESSENTIAL_CATEGORIES = {"groceries", "transport", "dining"}
FIXED_RECURRING_CATEGORIES = {
    "rent", "utilities", "education", "debt_repayment", "housing", "insurance",
    "music_subscription", "delivery_membership", "cloud_storage", "streaming",
    "entertainment", "gym", "healthcare",
}


def rent_increase_pct(user_id, messages_by_user):
    msgs = messages_by_user.get(user_id, [])
    pct = None
    latest_sent = None
    for m in msgs:
        action, text = classify(m["message_text"])
        if action == "RENT_INCREASE_PCT":
            p = extract_pct(text)
            if p is not None and (latest_sent is None or m["sent_at"] > latest_sent):
                pct = p
                latest_sent = m["sent_at"]
    return pct


def invoice_one_time_credits(user_id, messages_by_user):
    out = []
    for m in messages_by_user.get(user_id, []):
        action, text = classify(m["message_text"])
        if action == "INVOICE_CONFIRMED_ONE_TIME":
            amounts = extract_all_amounts(text)
            dates = extract_all_dates(text)
            if amounts and dates:
                out.append((dates[0], amounts[0][1], amounts[0][0]))
    return out


def build_forecast_events(user_id, profile, events, messages_by_user, rates_convert, request_date_s):
    """Return list of dicts: {date, amount_home(signed +credit/-debit), category, flexibility,
    event_id, kind:'recurring'|'known_future'|'salary'|'one_time'} within [request_date, +90d]."""
    req = pdate(request_date_s)
    end = (req + timedelta(days=WINDOW_DAYS)).isoformat()
    out = []

    # 1) Salary (income) recurring, with message overrides
    state, cadence, scheduled_next = build_salary_state(user_id, events, messages_by_user, request_date_s)
    salary_occ = project_salary(state, cadence, scheduled_next, request_date_s, end)

    for d, amt in salary_occ:
        out.append({"date": d, "amount_home": amt, "category": "salary", "flexibility": "fixed",
                     "event_id": None, "kind": "salary"})

    # 2) Fixed recurring categories (rent, utilities, education, debt_repayment, subscriptions, etc.)
    cats_seen = set(e["category"] for e in events if e["category"] not in ("salary",))
    for cat in cats_seen:
        if cat in NON_RECURRING_CATEGORIES:
            continue
        for direction in ("debit", "credit"):
            info = detect_generic_recurring(events, cat, direction, request_date_s)
            if not info:
                continue
            sample = info["sample_event"]
            flexibility = sample["flexibility"]
            amount = info["avg_amount"]
            if cat == "rent" and direction == "debit":
                pct = rent_increase_pct(user_id, messages_by_user)
                if pct:
                    amount = amount * (1 + pct / 100.0)
            nxt = step_date(info["last_date"], info["cadence"])
            while nxt < req:
                nxt = step_date(nxt, info["cadence"])
            while nxt.isoformat() <= end:
                signed = amount if direction == "credit" else -amount
                out.append({"date": nxt.isoformat(), "amount_home": signed, "category": cat,
                             "flexibility": flexibility, "event_id": f"recurring:{cat}",
                             "kind": "recurring"})
                nxt = step_date(nxt, info["cadence"])

    # 3) Known future committed events already in financial_events.csv: pending debits (reserved),
    #    scheduled debits/credits (excluding the salary ones handled above), settlement in window.
    for e in events:
        if e["status"] not in ("pending", "scheduled"):
            continue
        if e["category"] == "salary":
            continue  # handled above
        if not (request_date_s <= e["settlement_date"] <= end):
            continue
        if e["direction"] == "credit":
            continue  # do not count pending credits until settled
        out.append({"date": e["settlement_date"], "amount_home": -e["amount_home"], "category": e["category"],
                     "flexibility": e["flexibility"], "event_id": e["event_id"], "kind": "known_future"})

    # 4) One-time confirmed invoice income from messages (service_provider)
    home_ccy = profile["home_currency"]
    for d, amt, ccy in invoice_one_time_credits(user_id, messages_by_user):
        if request_date_s <= d <= end:
            amt_home = rates_convert(amt, ccy, home_ccy, d) if ccy != home_ccy else amt
            out.append({"date": d, "amount_home": amt_home, "category": "other_income",
                         "flexibility": "fixed", "event_id": None, "kind": "one_time"})

    return out
