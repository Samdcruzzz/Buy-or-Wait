import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from loaders import load_profiles, load_exchange_rates, load_events, load_messages, load_requests, load_payment_options, convert
from reconstruct import build_forecast_events
from decision_pipeline import decide_request

profiles = load_profiles()
rates = load_exchange_rates()
events = load_events(rates, profiles)
messages = load_messages()
payment_options = load_payment_options()
samples = load_requests("sample_requests.csv")


def rates_convert(amt, f, t, d):
    return convert(amt, f, t, d, rates)


n_status = 0
n_method = 0
n_amount = 0
total = 0
for r in samples:
    total += 1
    uid = r["user_id"]
    profile = profiles[uid]
    ev = events.get(uid, [])
    fevents = build_forecast_events(uid, profile, ev, messages, rates_convert, r["request_date"])
    popts = payment_options.get(r["request_id"], [])
    res = decide_request(r, profile, fevents, ev, popts)

    st_ok = res["affordability_status"] == r["affordability_status"]
    me_ok = res["recommended_payment_method"] == r["recommended_payment_method"]
    am_ok = abs(res["amount_safe_to_pay"] - float(r["amount_safe_to_pay"])) < 1.0
    n_status += st_ok
    n_method += me_ok
    n_amount += am_ok
    flag = "OK" if (st_ok and me_ok) else "XX"
    print(f"{flag} {r['request_id']} status:{res['affordability_status']:<22}(exp {r['affordability_status']:<22}) "
          f"method:{res['recommended_payment_method']:<15}(exp {r['recommended_payment_method']:<15}) "
          f"amt_ok={am_ok}")
    if not (st_ok and me_ok):
        print("    plan:", res["payment_plan"], "| exp:", r["payment_plan"])
        print("    chg :", res["spending_changes_needed"], "| exp:", r["spending_changes_needed"])

print(f"\nstatus {n_status}/{total}  method {n_method}/{total}  amount {n_amount}/{total}")
