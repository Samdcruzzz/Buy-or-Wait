import hashlib
from loaders import pdate
from forecast import amount_safe_to_pay, earliest_full_payment_date
from decide import (best_change_combo_for_full_today, build_installment_candidates,
                     whole_window_min_cushion)
from formatting import fmt_money, fmt_date_long, fmt_plan, fmt_spending_changes, category_label


def variant(request_id, n):
    """Deterministic pick in [0, n) from request_id, so explanation wording varies across
    requests (matching the stylistic variety in the reference decision_explanation strings)
    without introducing any run-to-run randomness."""
    if n <= 1:
        return 0
    h = hashlib.md5(request_id.encode("utf-8")).hexdigest()
    return int(h, 16) % n


REQUEST_TYPE_NOUN = {
    "purchase": "purchase", "travel": "trip", "education": "course or program",
    "family_transfer": "transfer", "debt_repayment": "repayment", "investment": "contribution",
    "housing": "housing payment", "emergency_expense": "expense", "other": "request",
}


def decide_request(request, profile, forecast_events, events_all, payment_options):
    request_date_s = request["request_date"]
    requested = float(request["requested_amount"])
    desired_s = request["desired_completion_date"]
    allows_partial = request["allows_partial_payment"].strip().lower() == "true"
    min_balance = profile["minimum_balance_to_keep"]
    current_balance = profile["current_available_balance"]
    ccy = profile["home_currency"]

    safe0, balances0, cushion0, dates0 = amount_safe_to_pay(
        current_balance, forecast_events, request_date_s, min_balance, requested)
    earliest0 = earliest_full_payment_date(
        current_balance, forecast_events, request_date_s, min_balance, requested)

    candidates = []

    if "full_payment" in profile["payment_methods"] and safe0 >= requested - 1e-6:
        candidates.append({
            "method": "full_payment", "changes": [], "completes_on_time": True,
            "total_paid": requested, "first_payment_date": request_date_s, "num_payments": 1,
            "payment_option_id": -1, "plan": [(request_date_s, requested)],
        })

    if "full_payment" in profile["payment_methods"] and safe0 < requested - 1e-6:
        details, fe_changed = best_change_combo_for_full_today(
            profile, forecast_events, events_all, request_date_s, current_balance, min_balance, requested)
        if details:
            candidates.append({
                "method": "full_payment", "changes": details, "completes_on_time": True,
                "total_paid": requested, "first_payment_date": request_date_s, "num_payments": 1,
                "payment_option_id": -1, "plan": [(request_date_s, requested)],
            })

    if (allows_partial and "partial_payment" in profile["payment_methods"]
            and 0 < safe0 < requested - 1e-6 and earliest0 is not None and earliest0 <= desired_s):
        candidates.append({
            "method": "partial_payment", "changes": [], "completes_on_time": True,
            "total_paid": requested, "first_payment_date": request_date_s, "num_payments": 2,
            "payment_option_id": -1, "plan": [(request_date_s, safe0), (earliest0, requested - safe0)],
        })

    inst_candidates = build_installment_candidates(
        payment_options, profile, forecast_events, request_date_s, current_balance, min_balance, desired_s)
    for ic in inst_candidates:
        if ic["safe"] and ic["completes_on_time"]:
            candidates.append({
                "method": "installments", "changes": [], "completes_on_time": True,
                "total_paid": ic["total_paid"], "first_payment_date": ic["first_payment_date"],
                "num_payments": ic["num_payments"], "payment_option_id": ic["payment_option_id"],
                "plan": list(zip(ic["dates"], [ic["option"]["payment_amount"]] * ic["num_payments"])),
            })

    if ("full_payment" in profile["payment_methods"] and earliest0 is not None
            and not (safe0 >= requested - 1e-6)):
        candidates.append({
            "method": "wait", "changes": [], "completes_on_time": earliest0 <= desired_s,
            "total_paid": requested, "first_payment_date": earliest0, "num_payments": 1,
            "payment_option_id": -1, "plan": [(earliest0, requested)],
        })

    result = {
        "request_id": request["request_id"],
        "amount_safe_to_pay": round(min(max(safe0, 0.0), requested), 2),
        "earliest_date_for_full_payment": earliest0 or "",
    }

    if not candidates:
        result["affordability_status"] = "not_affordable"
        result["recommended_payment_method"] = "not_recommended"
        result["payment_plan"] = "none"
        result["spending_changes_needed"] = "none"
        result["decision_explanation"] = build_not_affordable_explanation(
            request["request_id"], request.get("request_type", "other"), ccy, requested, safe0, min_balance)
        return result

    def keyfn(c):
        return (
            0 if c["completes_on_time"] else 1,
            len(c["changes"]),
            round(c["total_paid"], 2),
            c["first_payment_date"],
            c["num_payments"],
            c["payment_option_id"] if isinstance(c["payment_option_id"], str) else "",
        )

    candidates.sort(key=keyfn)
    best = candidates[0]

    if best["method"] == "full_payment" and best["first_payment_date"] == request_date_s and not best["changes"]:
        status = "affordable_now"
    elif best["method"] == "wait":
        status = "affordable_later"
    else:
        status = "affordable_with_plan"

    result["affordability_status"] = status
    result["recommended_payment_method"] = best["method"]
    result["payment_plan"] = fmt_plan(best["plan"])
    result["spending_changes_needed"] = fmt_spending_changes(best["changes"])
    result["decision_explanation"] = build_explanation(
        request["request_id"], request.get("request_type", "other"), status, best, ccy, min_balance, requested, safe0)
    return result


def build_explanation(request_id, request_type, status, best, ccy, min_balance, requested, safe0):
    method = best["method"]
    noun = REQUEST_TYPE_NOUN.get(request_type, "request")
    v = variant(request_id, 2)

    if status == "affordable_now":
        if v == 0:
            return (f"Pay {fmt_money(ccy, requested)} today for this {noun}. Balance stays at or above "
                     f"the {fmt_money(ccy, min_balance)} minimum for the full 90-day outlook.")
        return (f"The full {fmt_money(ccy, requested)} is safe to pay today: projected balance never "
                f"drops below the {fmt_money(ccy, min_balance)} minimum over the next 90 days.")

    if method == "full_payment":  # affordable_with_plan via a permitted spending change
        change_phrases = []
        for cat, action, ref_id, min_allowed in best["changes"]:
            label = category_label(cat)
            if action == "stop":
                change_phrases.append(f"stopping the {label}")
            else:
                change_phrases.append(f"reducing the {label} to {fmt_money(ccy, min_allowed)}")
        changes_text = " and ".join(change_phrases)
        if v == 0:
            return (f"Paying the full {fmt_money(ccy, requested)} today only stays safe by "
                     f"{changes_text}; with that change, the {fmt_money(ccy, min_balance)} minimum "
                     f"holds for the next 90 days.")
        return (f"By {changes_text}, the full {fmt_money(ccy, requested)} can be paid today for this "
                f"{noun} without breaking the {fmt_money(ccy, min_balance)} minimum balance.")

    if method == "partial_payment":
        d0, a0 = best["plan"][0]
        d1, a1 = best["plan"][1]
        if v == 0:
            return (f"Pay {fmt_money(ccy, a0)} today and the remaining {fmt_money(ccy, a1)} on "
                     f"{fmt_date_long(d1)}. Together these complete the {fmt_money(ccy, requested)} {noun} "
                     f"while keeping the {fmt_money(ccy, min_balance)} minimum protected throughout.")
        return (f"Only {fmt_money(ccy, a0)} is safe to pay today toward this {fmt_money(ccy, requested)} "
                f"{noun}; the balance is projected to recover enough to safely cover the remaining "
                f"{fmt_money(ccy, a1)} by {fmt_date_long(d1)}.")

    if method == "installments":
        n = best["num_payments"]
        amt = best["plan"][0][1]
        start = best["first_payment_date"]
        if v == 0:
            return (f"Use the {n}-payment installment plan of {fmt_money(ccy, amt)} each, starting "
                     f"{fmt_date_long(start)}. Every payment stays clear of the {fmt_money(ccy, min_balance)} "
                     f"minimum balance.")
        return (f"Spread this {fmt_money(ccy, requested)} {noun} across {n} installments of "
                f"{fmt_money(ccy, amt)} beginning {fmt_date_long(start)} rather than paying in full; "
                f"this is the safest plan that completes on time.")

    if method == "wait":
        d, amt = best["plan"][0]
        if v == 0:
            return (f"Wait until {fmt_date_long(d)} to pay the full {fmt_money(ccy, amt)}. Paying sooner "
                     f"would push the balance below the {fmt_money(ccy, min_balance)} minimum before then.")
        return (f"The full {fmt_money(ccy, amt)} for this {noun} is not safe to pay yet, but the forecast "
                f"shows it becomes safe by {fmt_date_long(d)} without needing any spending changes.")

    return "Review this request manually."


def build_not_affordable_explanation(request_id, request_type, ccy, requested, safe0, min_balance):
    noun = REQUEST_TYPE_NOUN.get(request_type, "request")
    safe = max(safe0, 0.0)
    shortfall = requested - safe
    v = variant(request_id, 2)
    if v == 0:
        return (f"Do not proceed with this {fmt_money(ccy, requested)} {noun} yet. Only "
                 f"{fmt_money(ccy, safe)} can be paid today without risking the {fmt_money(ccy, min_balance)} "
                 f"minimum, and the remaining {fmt_money(ccy, shortfall)} is not projected to become safe "
                 f"within the 90-day forecast.")
    return (f"This {fmt_money(ccy, requested)} {noun} cannot be completed safely within 90 days: at most "
            f"{fmt_money(ccy, safe)} is available today, {fmt_money(ccy, shortfall)} short of the full "
            f"amount, with no supported installment or spending-change option that closes the gap.")
