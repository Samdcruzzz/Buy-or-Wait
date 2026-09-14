from datetime import datetime

CATEGORY_LABELS = {
    "cloud_storage": "online backup subscription",
    "music_subscription": "music subscription",
    "delivery_membership": "delivery membership",
    "streaming": "streaming subscription",
    "entertainment": "entertainment spending",
    "dining": "dining spending",
    "gym": "gym membership",
    "shopping": "shopping spending",
}


def category_label(cat):
    return CATEGORY_LABELS.get(cat, cat.replace("_", " "))


def fmt_amount(v):
    v = round(float(v), 2)
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def fmt_money(ccy, v):
    return f"{ccy} {fmt_amount(v)}"


def fmt_date_long(date_s):
    d = datetime.strptime(date_s, "%Y-%m-%d")
    return d.strftime("%-d %B %Y")


def fmt_plan(plan_pairs):
    if not plan_pairs:
        return "none"
    parts = []
    for d, amt in plan_pairs:
        v = round(float(amt), 2)
        if abs(v - round(v)) < 0.005:
            s = str(int(round(v)))
        else:
            s = f"{v:.2f}"
        parts.append(f"{d}:{s}")
    return "|".join(parts)


def fmt_spending_changes(changes):
    if not changes:
        return "none"
    parts = []
    for cat, action, ref_id, min_allowed in changes[:3]:
        if action == "stop":
            parts.append(f"stop:{ref_id}")
        else:
            v = round(float(min_allowed), 2)
            s = str(int(round(v))) if abs(v - round(v)) < 0.005 else f"{v:.2f}"
            parts.append(f"reduce_to:{ref_id}:{s}")
    return "|".join(parts)
