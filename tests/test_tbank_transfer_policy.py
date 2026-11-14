from dataclasses import replace

import pytest
from sqlalchemy import select

from backend.categorization import classify, requires_manual_review
from backend.database import CategoryRule, Transaction, User
from test_app import clients, upload, confirm, certificate

SBP = 'Пополнение. Система быстрых платежей'
CONTRACT = 'Внутрибанковский перевод с договора 1234567890'


@pytest.mark.parametrize('description', [SBP, 'Пополнение через СБП. АО "ЯНДЕКС БАНК"', 'Перевод по СБП'])
def test_anonymous_sbp_policy_is_incoming_and_tbank_only(description):
    assert requires_manual_review('tbank', description, 100)
    assert not requires_manual_review('yandex', description, 100)
    assert not requires_manual_review('tbank', description, -100)


@pytest.mark.parametrize('description', [CONTRACT, 'Перевод с договора 1234567890', 'Внутрибанковский перевод с договора Т-Банк'])
def test_contract_receipts_income_with_bank_scope_and_sign(description):
    assert classify(description, 100, bank='tbank') == ('Доход', 'income')
    assert classify(description, -100, bank='tbank')[1] == 'review'
    assert classify(description, 100, bank='yandex')[1] == 'review'
    assert not requires_manual_review('tbank', description, 100)


def test_new_sbp_ignores_old_rule_and_manual_edit_never_changes_other_rows(clients, monkeypatch):
    app, a, csrf, _, _ = clients
    base = certificate().transactions[0]
    def row(description, day):
        return replace(base, description=description, amount_minor=10000, original_amount_minor=10000,
                       occurred_at=f'2026-10-{day:02d}T12:00:00')
    old = row(SBP, 10)
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, certificate([old]), b'%PDF-old')).status_code == 200
    with app.state.sessions() as db:
        uid = db.scalar(select(User.id).where(User.email == 'alice@example.com'))
        t = db.scalar(select(Transaction).where(Transaction.user_id == uid))
        t.kind, t.category, t.manual = 'transfer', 'Между своими счетами', True
        old_id = t.id
        db.add(CategoryRule(user_id=uid, description=SBP, direction=1, kind='transfer', category='Между своими счетами'))
        db.commit()
    new = row(SBP, 11)
    contract = row(CONTRACT, 12)
    parsed = certificate([old, new, contract])
    preview = upload(a, csrf, monkeypatch, parsed, b'%PDF-overlap')
    assert preview['summary']['duplicates'] == 1 and preview['summary']['new'] == 2
    assert confirm(a, csrf, preview).status_code == 200
    items = a.get('/api/transactions').json()['items']
    assert next(t for t in items if t['id'] == old_id)['kind'] == 'transfer'
    fresh = next(t for t in items if t['occurred_at'] == new.occurred_at)
    assert fresh['kind'] == 'review' and not fresh['manual'] and not fresh['can_remember']
    receipt = next(t for t in items if t['description'] == CONTRACT)
    assert receipt['kind'] == 'income' and receipt['can_remember']
    # Even an old browser requesting "remember" may change only this receipt.
    response = a.patch('/api/transactions/' + fresh['id'], headers=csrf,
                       json={'kind': 'income', 'category': 'Доход', 'remember': True})
    assert response.status_code == 200 and response.json()['affected'] == 1
    later = row(SBP, 13)
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, certificate([later]), b'%PDF-later')).status_code == 200
    items = a.get('/api/transactions').json()['items']
    assert next(t for t in items if t['id'] == old_id)['kind'] == 'transfer'
    assert next(t for t in items if t['id'] == fresh['id'])['kind'] == 'income'
    assert next(t for t in items if t['occurred_at'] == later.occurred_at)['kind'] == 'review'
    # Re-uploading overlapping history preserves both earlier decisions.
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, parsed, b'%PDF-repeat')).status_code == 200
    assert a.get('/api/transactions').json()['total'] == 4


def test_contract_receipts_keep_explicit_personal_rule(clients, monkeypatch):
    app, a, csrf, _, _ = clients
    with app.state.sessions() as db:
        uid = db.scalar(select(User.id).where(User.email == 'alice@example.com'))
        db.add(CategoryRule(user_id=uid, description=CONTRACT, direction=1, kind='transfer', category='Между своими счетами'))
        db.commit()
    t = replace(certificate().transactions[0], description=CONTRACT, amount_minor=10000, original_amount_minor=10000)
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, certificate([t]))).status_code == 200
    assert a.get('/api/transactions').json()['items'][0]['kind'] == 'transfer'
