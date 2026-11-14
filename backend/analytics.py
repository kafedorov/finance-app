"""Read-only, bounded analytics. Group transactions in SQL; never return raw history."""
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import case, func, select

from .database import Document, Snapshot, Transaction
from .services import scoped_accounts


def month_shift(value, offset):
    index = value.year * 12 + value.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, min(value.day, monthrange(year, month + 1)[1]))


def days(start, end):
    for i in range(max(0, (end - start).days + 1)):
        yield start + timedelta(days=i)


def merge_intervals(values):
    result = []
    for start, end in sorted(values):
        if result and start <= result[-1][1] + timedelta(days=1):
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def coverage_intervals(db, uid, accounts):
    ids = [a.id for a in accounts if a.kind in {"card", "savings"}]
    mappings = defaultdict(set)
    for doc_id, aid in db.execute(select(Transaction.document_id, Transaction.account_id).where(Transaction.user_id == uid, Transaction.account_id.in_(ids)).distinct()):
        mappings[doc_id].add(aid)
    for aid, details in db.execute(select(Snapshot.account_id, Snapshot.details).where(Snapshot.user_id == uid, Snapshot.account_id.in_(ids))):
        if details.get("document_id"):
            mappings[details["document_id"]].add(aid)
    result = defaultdict(list)
    for doc in db.scalars(select(Document).where(Document.user_id == uid, Document.status == "imported")):
        if doc.summary.get("kind") != "movement":
            continue
        try:
            start, end = date.fromisoformat(doc.summary["period_start"]), date.fromisoformat(doc.summary["period_end"])
        except (ValueError, KeyError, TypeError):
            continue
        for aid in mappings[doc.id] | (set(doc.summary.get("account_ids", [])) & set(ids)):
            result[aid].append((start, end))
    return {aid: merge_intervals(result[aid]) for aid in ids}


def coverage_state(intervals, start, end):
    if not intervals or start > end:
        return "missing"
    full = partial = 0
    for day in days(start, end):
        active = [values for values in intervals.values() if not values or day >= values[0][0]]
        covered = [any(a <= day <= b for a, b in values) for values in active]
        full += bool(covered) and all(covered)
        partial += any(covered)
    if full == (end - start).days + 1:
        return "complete"
    return "partial" if partial else "missing"


def build_analytics(db, uid, start, end, bank="", account_id="", bucket="month"):
    accounts = scoped_accounts(db, uid, bank)
    if account_id:
        accounts = [a for a in accounts if a.id == account_id]
    ids = [a.id for a in accounts]
    scope = [Transaction.user_id == uid, Transaction.account_id.in_(ids), Transaction.currency == "RUB"]
    intervals = coverage_intervals(db, uid, accounts)
    known = [values[-1][1] for values in intervals.values() if values]
    last_transaction = db.scalar(select(func.max(Transaction.occurred_at)).where(*scope))
    # A stale account must mark the combined report partial, not hide newer
    # operations from other banks. Completeness is checked account by account.
    anchor = min(end, max(known)) if known else min(end, date.fromisoformat(last_transaction[:10])) if last_transaction else end
    first_transaction = db.scalar(select(func.min(Transaction.occurred_at)).where(*scope))
    if start.year < 1950:
        start = date.fromisoformat(first_transaction[:10]) if first_transaction else anchor
    # Bound arbitrary requests while keeping multiple years available.
    start = max(start, month_shift(anchor.replace(day=1), -119))
    effective_end = max(start - timedelta(days=1), anchor)
    full_month = start.day == 1 and end == date(end.year, end.month, monthrange(end.year, end.month)[1]) and start.month == end.month and start.year == end.year
    if full_month:
        previous_start = month_shift(start, -1)
        previous_end = date(previous_start.year, previous_start.month, monthrange(previous_start.year, previous_start.month)[1]) if effective_end == end else month_shift(effective_end, -1)
    else:
        span = max(1, (effective_end - start).days + 1)
        previous_end, previous_start = start - timedelta(days=1), start - timedelta(days=span)
    month_end = anchor.replace(day=1)
    month_start = max(month_shift(month_end, -23), min(start.replace(day=1), month_shift(month_end, -11)))
    query_start = min(start, previous_start, month_start)
    day_col = func.substr(Transaction.occurred_at, 1, 10)
    interest = case(((Transaction.kind == "income") & (Transaction.amount_minor > 0) & Transaction.description.ilike("%процент%") & Transaction.account_id.in_([a.id for a in accounts if a.kind in {"savings", "deposit"}]), Transaction.amount_minor), else_=0)
    rows = list(db.execute(select(day_col, Transaction.category, Transaction.kind, func.sum(Transaction.amount_minor), func.count(), func.sum(interest)).where(*scope, Transaction.occurred_at >= query_start.isoformat(), Transaction.occurred_at < (anchor + timedelta(days=1)).isoformat()).group_by(day_col, Transaction.category, Transaction.kind)))
    current, previous, category_current, category_previous, category_counts = Counter(), Counter(), Counter(), Counter(), Counter()
    daily = defaultdict(Counter)
    month_values = defaultdict(Counter)
    monthly_counts = defaultdict(Counter)
    monthly_cash = defaultdict(Counter)
    for stamp, category, kind, amount, count, earned in rows:
        day = date.fromisoformat(stamp)
        expense = -amount if kind == "expense" and amount < 0 else 0
        income = amount if kind == "income" and amount > 0 else 0
        if month_start <= day <= anchor:
            month_values[stamp[:7]][category] += expense
            monthly_counts[stamp[:7]][category] += count if expense else 0
            monthly_cash[stamp[:7]]["expense"] += expense
            monthly_cash[stamp[:7]]["income"] += income
            monthly_cash[stamp[:7]]["interest"] += earned or 0
        if query_start <= day <= anchor:
            daily[stamp][category] += expense
        target = current if start <= day <= effective_end else previous if previous_start <= day <= previous_end else None
        if target is not None:
            target["expenses_minor"] += expense
            target["income_minor"] += income
            target["interest_minor"] += earned or 0
            target["expense_count"] += count if expense else 0
            target["refunds_minor"] += amount if kind == "refund" and amount > 0 else 0
            target["review_out_minor"] += -amount if kind == "review" and amount < 0 else 0
            target["review_in_minor"] += amount if kind == "review" and amount > 0 else 0
            if expense:
                (category_current if target is current else category_previous)[category] += expense
                if target is current:
                    category_counts[category] += count
    def totals(counter):
        result = {key: counter[key] for key in ("expenses_minor", "income_minor", "interest_minor", "expense_count", "refunds_minor", "review_out_minor", "review_in_minor")}
        result["net_minor"] = result["income_minor"] - result["expenses_minor"]
        return result
    category_names = set(category_current) | set(category_previous) | {c for v in month_values.values() for c, n in v.items() if n}
    categories = []
    for name in sorted(category_names, key=lambda n: (-category_current[n], -sum(v[n] for v in month_values.values()), n)):
        amount, old = category_current[name], category_previous[name]
        categories.append({"name": name, "amount_minor": amount, "previous_minor": old, "change_minor": amount-old, "change_pct": round((amount-old)/old*100, 1) if old else None, "count": category_counts[name], "average_minor": round(amount/category_counts[name]) if category_counts[name] else 0})
    months = []
    cursor = month_start
    while cursor <= month_end:
        stop = min(date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]), anchor)
        state = coverage_state(intervals, cursor, stop)
        months.append({"date": cursor.isoformat()[:7], "end": stop.isoformat(), "coverage": state, "categories": dict(month_values[cursor.isoformat()[:7]]), "counts": dict(monthly_counts[cursor.isoformat()[:7]]), **{key+"_minor": monthly_cash[cursor.isoformat()[:7]][key] for key in ("expense", "income", "interest")}})
        cursor = month_shift(cursor, 1)
    # Day/week charts have a fixed maximum number of plotted columns.
    used_bucket = bucket
    if bucket == "day" and (effective_end-start).days > 180:
        used_bucket = "week"
    if used_bucket == "week" and (effective_end-start).days > 900:
        used_bucket = "month"
    points = []
    if used_bucket == "month":
        points = [{"date": m["date"]+"-01", "end": m["end"], "coverage": m["coverage"], "categories": m["categories"]} for m in months]
    else:
        cursor = start
        while cursor <= effective_end:
            stop = min(effective_end, cursor + timedelta(days=6 if used_bucket == "week" else 0))
            values = Counter()
            for day in days(cursor, stop):
                values.update(daily[day.isoformat()])
            points.append({"date": cursor.isoformat(), "end": stop.isoformat(), "coverage": coverage_state(intervals, cursor, stop), "categories": dict(values)})
            cursor = stop + timedelta(days=1)
    # Pace compares aligned days within the selected current and previous month.
    pace = []
    if full_month and start <= effective_end:
        running = old_running = 0
        for offset, day in enumerate(days(start, effective_end)):
            old_day = previous_start + timedelta(days=offset)
            running += sum(daily[day.isoformat()].values())
            if old_day <= previous_end:
                old_running += sum(daily[old_day.isoformat()].values())
            pace.append({"date": day.isoformat(), "end": day.isoformat(), "current_minor": running, "previous_minor": old_running if old_day <= previous_end else None, "coverage": coverage_state(intervals, day, day), "previous_coverage": coverage_state(intervals, old_day, old_day) if old_day <= previous_end else "missing"})
    return {"period": {"start": start.isoformat(), "end": effective_end.isoformat(), "requested_end": end.isoformat()}, "previous_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()}, "coverage": coverage_state(intervals, start, effective_end), "previous_coverage": coverage_state(intervals, previous_start, previous_end), "as_of": anchor.isoformat() if known or last_transaction else None, "current": totals(current), "previous": totals(previous), "categories": categories, "points": points, "months": months, "pace": pace, "bucket": used_bucket, "account_ids": ids}
