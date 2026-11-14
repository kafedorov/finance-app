from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select

from .categorization import classify, requires_manual_review, transfer_phones
from .categories import category_names
from .database import Account, CategoryRule, Document, Snapshot, Transaction
from .importers.registry import bank_name


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(row: dict) -> str:
    # The posting time may settle later; it is deliberately not an identity field.
    fields = [row[k] for k in ("occurred_at", "amount_minor", "currency", "original_amount_minor", "original_currency", "card_last4")]
    fields.append(" ".join(row["description"].casefold().split()))
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def weak_key(row):
    return (row["occurred_at"], row["amount_minor"], row["currency"], row.get("card_last4"))


def own_transfer_phones(db, user_id):
    """Only the current user's explicit own-transfer decisions teach identity."""
    descriptions = list(db.scalars(select(CategoryRule.description).where(CategoryRule.user_id == user_id, CategoryRule.direction == 1, CategoryRule.kind == "transfer")))
    descriptions.extend(db.scalars(select(Transaction.description).where(Transaction.user_id == user_id, Transaction.amount_minor > 0, Transaction.kind == "transfer", Transaction.manual.is_(True))))
    return set().union(*(transfer_phones(d) for d in descriptions))


def classify_incoming_history(db, user_id):
    """Apply incoming-person defaults to unclassified history of one profile."""
    phones = own_transfer_phones(db, user_id)
    changed = Counter()
    for t in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.amount_minor > 0, Transaction.kind == "review")):
        category, kind = classify(t.description, t.amount_minor, phones)
        if kind == "income" and category == "Переводы от людей":
            t.category, t.kind = category, kind
            changed["income"] += 1
        elif kind == "transfer" and transfer_phones(t.description).intersection(phones):
            t.category, t.kind = category, kind
            changed["own_transfer"] += 1
    # Keep an old "needs review" remembered decision from undoing this change.
    for r in db.scalars(select(CategoryRule).where(CategoryRule.user_id == user_id, CategoryRule.direction == 1, CategoryRule.kind == "review")):
        category, kind = classify(r.description, 1, phones)
        if kind in {"income", "transfer"} and (category == "Переводы от людей" or transfer_phones(r.description).intersection(phones)):
            r.category, r.kind = category, kind
            changed["rules"] += 1
    return dict(changed)


def import_plan(db, user_id: str, payload: dict):
    rows = payload["transactions"]
    external_key = payload["snapshots"][0]["account_key"]
    provider = payload.get("bank", "tbank")
    account = db.scalar(select(Account).where(Account.user_id == user_id, Account.bank == provider, Account.external_key == external_key))
    existing = list(db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.account_id == account.id))) if account else []
    counts = Counter(t.fingerprint for t in existing)
    weak = defaultdict(set)
    for t in existing:
        weak[(t.occurred_at, t.amount_minor, t.currency, t.card_last4)].add(t.fingerprint)
    incoming = Counter()
    planned = []
    for row in rows:
        fp = fingerprint(row)
        incoming[fp] += 1
        status = "duplicate" if incoming[fp] <= counts[fp] else "new"
        if status == "new" and weak.get(weak_key(row)) and fp not in weak[weak_key(row)]:
            status = "ambiguous"
        planned.append((row, fp, incoming[fp], status))
    return planned


def preview_summary(db, user_id: str, payload: dict):
    plan = import_plan(db, user_id, payload)
    counts = Counter(item[3] for item in plan)
    latest = {}
    for snapshot in payload["snapshots"]:
        if snapshot["account_key"] not in latest or snapshot["as_of"] >= latest[snapshot["account_key"]]["as_of"]:
            latest[snapshot["account_key"]] = snapshot
    return {"kind": payload["kind"], "account_kind": payload.get("account_kind"), "history_points": len(payload["snapshots"]), "adapter": payload["adapter_version"], "period_start": payload["period_start"], "period_end": payload["period_end"], "total": len(plan), "new": counts["new"], "duplicates": counts["duplicate"], "ambiguous": counts["ambiguous"], "credits_minor": payload["credits_minor"], "debits_minor": payload["debits_minor"], "snapshots": [{k: s[k] for k in ("account_last4", "as_of", "amount_minor", "currency")} for s in latest.values()], "sample": [{**row, "status": status} for row, _, _, status in plan if status != "duplicate"][:8]}


def persist_import(db, doc: Document):
    payload = doc.payload
    plan = import_plan(db, doc.user_id, payload)
    if any(status == "ambiguous" for _, _, _, status in plan):
        raise ValueError("Есть похожие операции с измененными описаниями. Импорт остановлен: нужна проверка совпадений.")
    accounts = {}
    provider = payload.get("bank", "tbank")
    for s in payload["snapshots"]:
        account = db.scalar(select(Account).where(Account.user_id == doc.user_id, Account.bank == provider, Account.external_key == s["account_key"]).with_for_update())
        if not account:
            kind = payload.get("account_kind") or ("card" if payload["kind"] == "movement" else "deposit")
            label = {"card": "Карта", "deposit": "Вклад", "savings": "Накопительный счет"}[kind]
            account = Account(user_id=doc.user_id, bank=provider, institution=provider, external_key=s["account_key"], name=f"{label} · {bank_name(provider)}", kind=kind, currency=s["currency"], last4=s["account_last4"])
            db.add(account)
            db.flush()
        elif payload.get("account_kind") == "savings" and account.kind == "deposit":
            account.kind = "savings"
            account.name = f"Накопительный счет · {bank_name(provider)}"
        accounts[s["account_key"]] = account
        snapshot = db.scalar(select(Snapshot).where(Snapshot.user_id == doc.user_id, Snapshot.account_id == account.id, Snapshot.as_of == s["as_of"], Snapshot.source == provider))
        if not snapshot:
            snapshot = Snapshot(user_id=doc.user_id, account_id=account.id, as_of=s["as_of"], amount_minor=s["amount_minor"], source=provider, details={"balance_type": s.get("balance_type", "available"), "document_id": doc.id})
            db.add(snapshot)
        else:
            snapshot.amount_minor = s["amount_minor"]
            snapshot.details = {"balance_type": s.get("balance_type", "available"), "document_id": doc.id}
    rules = {(r.description, r.direction): (r.category, r.kind) for r in db.scalars(select(CategoryRule).where(CategoryRule.user_id == doc.user_id))}
    own_phones = own_transfer_phones(db, doc.user_id)
    count = 0
    account = accounts[payload["snapshots"][0]["account_key"]]
    for row, fp, occurrence, status in plan:
        if status == "duplicate":
            continue
        rule_key = (row["description"], -1 if row["amount_minor"] < 0 else 1)
        individual = requires_manual_review(provider, row["description"], row["amount_minor"])
        if individual:
            category, kind = "Нужно уточнить", "review"
        else:
            category, kind = rules.get(rule_key, classify(row["description"], row["amount_minor"], own_phones, bank=provider))
        db.add(Transaction(user_id=doc.user_id, account_id=account.id, document_id=doc.id, fingerprint=fp, occurrence=occurrence, category=category, kind=kind, manual=not individual and rule_key in rules, **row))
        count += 1
    doc.summary = preview_summary_before_commit(payload, plan, count)
    doc.status = "imported"
    doc.payload = {}
    return doc.summary


def preview_summary_before_commit(payload, plan, count):
    return {"kind": payload["kind"], "total": len(plan), "added": count, "duplicates": sum(status == "duplicate" for _, _, _, status in plan), "period_start": payload["period_start"], "period_end": payload["period_end"], "snapshots": len(payload["snapshots"])}


def transaction_dict(t, account=None):
    result = {k: getattr(t, k) for k in ("id", "account_id", "occurred_at", "posted_at", "amount_minor", "currency", "original_amount_minor", "original_currency", "description", "card_last4", "category", "kind", "manual", "source_page", "review_acknowledged")}
    if account:
        result.update(account_name=account.name, account_last4=account.last4, account_kind=account.kind)
        result["can_remember"] = not requires_manual_review(account.bank, t.description, t.amount_minor)
    return result


def account_dict(account, snapshots):
    latest = snapshots[-1] if snapshots else None
    previous = snapshots[-2] if len(snapshots) > 1 else None
    return {"id": account.id, "name": account.name, "bank": account.bank, "institution": account.institution, "bank_name": bank_name(account.institution), "is_hidden": account.is_hidden, "kind": account.kind, "currency": account.currency, "last4": account.last4, "source_url": account.source_url, "last_error": account.last_error, "as_of": latest.as_of if latest else None, "amount_minor": latest.amount_minor if latest else None, "change_minor": latest.amount_minor - previous.amount_minor if latest and previous else None, "details": latest.details if latest else {}, "history": [{"date": s.as_of, "amount_minor": s.amount_minor} for s in snapshots]}


def scoped_accounts(db, user_id, bank=None, include_hidden=False):
    query = select(Account).where(Account.user_id == user_id)
    if bank and bank != "all":
        query = query.where(Account.institution.is_(None) if bank == "unassigned" else Account.institution == bank)
    if not include_hidden:
        query = query.where(Account.is_hidden.is_(False))
    return list(db.scalars(query.order_by(Account.kind, Account.name)))


def acknowledge_reviews(db, user_id, bank=None):
    ids = [a.id for a in scoped_accounts(db, user_id, bank)]
    return db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.account_id.in_(ids), Transaction.kind == "review", Transaction.review_acknowledged.is_(False)).update({"review_acknowledged": True}, synchronize_session=False)


def dashboard(db, user_id, start, end, bank=None, include_hidden=False):
    all_accounts = scoped_accounts(db, user_id, include_hidden=True)
    candidates = [a for a in all_accounts if not bank or bank == "all" or (a.institution or "unassigned") == bank]
    accounts = candidates if include_hidden else [a for a in candidates if not a.is_hidden]
    account_ids = [a.id for a in accounts]
    by_id = {a.id: a for a in accounts}
    snapshots = list(db.scalars(select(Snapshot).where(Snapshot.user_id == user_id).order_by(Snapshot.as_of, Snapshot.id)))
    grouped = defaultdict(list)
    for s in snapshots:
        grouped[s.account_id].append(s)
    account_list = [account_dict(a, grouped[a.id]) for a in accounts]
    hidden_accounts = [account_dict(a, grouped[a.id]) for a in candidates if a.is_hidden]
    bank_ids = sorted({a.institution or "unassigned" for a in all_accounts})
    tx_scope = [Transaction.user_id == user_id, Transaction.account_id.in_(account_ids)]
    txs = list(db.scalars(select(Transaction).where(*tx_scope, Transaction.occurred_at >= start, Transaction.occurred_at < end + "T99").order_by(Transaction.occurred_at.desc())))
    rub = [t for t in txs if t.currency == "RUB"]
    expenses = [t for t in rub if t.kind == "expense" and t.amount_minor < 0]
    cats, days = Counter(), Counter()
    for t in expenses:
        cats[t.category] += -t.amount_minor
        days[t.occurred_at[:10]] += -t.amount_minor
    refunds = sum(t.amount_minor for t in rub if t.kind == "refund" and t.amount_minor > 0)
    monthly = Counter()
    for t in db.scalars(select(Transaction).where(*tx_scope, Transaction.currency == "RUB", Transaction.kind == "expense", Transaction.amount_minor < 0)):
        monthly[t.occurred_at[:7]] += -t.amount_minor
    total = sum(a["amount_minor"] or 0 for a in account_list if a["currency"] == "RUB")
    return {"expense_categories": category_names(db, user_id), "accounts": account_list, "hidden_accounts": hidden_accounts, "banks": [{"id": k, "name": bank_name(k)} for k in bank_ids], "selected_bank": bank or "all", "total_minor": total, "period": {"start": start, "end": end}, "expenses_minor": sum(-t.amount_minor for t in expenses), "refunds_minor": refunds, "income_minor": sum(t.amount_minor for t in rub if t.kind == "income" and t.amount_minor > 0), "review_count": sum(t.kind == "review" and not t.review_acknowledged for t in txs), "review_total_count": sum(t.kind == "review" for t in txs), "review_out_minor": -sum(t.amount_minor for t in rub if t.kind == "review" and t.amount_minor < 0), "all_review_count": db.query(Transaction).filter(*tx_scope, Transaction.kind == "review", Transaction.review_acknowledged.is_(False)).count(), "transaction_count": len(txs), "expense_count": len(expenses), "categories": [{"name": c, "amount_minor": v} for c, v in cats.most_common()], "daily": [{"date": d, "amount_minor": v} for d, v in sorted(days.items())], "monthly": [{"date": d, "amount_minor": v} for d, v in sorted(monthly.items())[-12:]], "recent": [transaction_dict(t, by_id[t.account_id]) for t in txs[:6]], "largest": [transaction_dict(t, by_id[t.account_id]) for t in sorted(expenses, key=lambda t: t.amount_minor)[:5]], "documents": [{"id": d.id, "filename": d.filename, "status": d.status, "created_at": d.created_at, "summary": d.summary} for d in db.scalars(select(Document).where(Document.user_id == user_id, Document.status == "imported").order_by(Document.created_at.desc()).limit(20))]}
