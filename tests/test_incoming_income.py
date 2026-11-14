from dataclasses import replace

import pytest
from sqlalchemy import select

from backend.categorization import classify, transfer_phones
from backend.database import CategoryRule, Transaction, User
from backend.services import classify_incoming_history
from test_app import clients, upload, confirm, certificate

OWN = 'Входящий перевод СБП, Иван Иванович И., +7 900 000-00-01, Банк А'
OWN_OTHER_BANK = 'Входящий перевод СБП, Иван Иванович И., 8 (900) 000-00-01, Банк Б'
OTHER = 'Входящий перевод СБП, Анна Игоревна А., +7 900 000-00-02, Банк А'


@pytest.mark.parametrize('description,amount,kind', [
    (OTHER, 10000, 'income'),
    (OTHER, -10000, 'review'),
    ('Входящий перевод СБП, Надир Илхамиз оглы Г., +7 900 000-00-03, Банк', 100, 'income'),
    ('Перевод между счетами одного клиента', 100, 'transfer'),
    ('Перевод себе', 100, 'transfer'),
    ('Возврат покупки', 100, 'refund'),
    ('Входящий перевод с карты *1111', 100, 'review'),
    ('Входящий перевод СБП, +7 900 000-00-03', 100, 'review'),
    ('Пополнение. Система быстрых платежей', 100, 'review'),
    ('Внесение наличных через банкомат', 100, 'review'),
])
def test_incoming_transfer_classification(description, amount, kind):
    assert classify(description, amount)[1] == kind


def test_known_owner_phone_across_banks_but_not_matching_name_alone():
    phones = transfer_phones(OWN)
    assert phones == {'79000000001'}
    assert classify(OWN_OTHER_BANK, 100, phones)[1] == 'transfer'
    assert classify('Входящий перевод СБП, +7 900 000-00-01', 100, phones)[1] == 'transfer'
    assert classify(OWN.replace('00-01', '00-02'), 100, phones)[1] == 'income'
    assert not transfer_phones('Внутрибанковский перевод с договора 79000000001123456789')


def test_existing_all_months_user_isolation_future_import_and_manual_rules(clients, monkeypatch):
    app, a, csrf, b, csrf2 = clients
    base = certificate().transactions[0]
    def row(description, stamp):
        return replace(base, description=description, amount_minor=10000, original_amount_minor=10000, occurred_at=stamp)
    rows = (row(OWN, '2026-09-12T10:00:00'), row(OWN_OTHER_BANK, '2026-10-12T10:00:00'),
            row(OTHER, '2026-09-12T11:00:00'), row(OTHER, '2026-10-12T11:00:00'),
            row('Пополнение. Система быстрых платежей', '2026-10-12T12:00:00'))
    for client, token, content in [(a, csrf, b'%PDF-a'), (b, csrf2, b'%PDF-b')]:
        assert confirm(client, token, upload(client, token, monkeypatch, certificate(rows), content)).status_code == 200
    with app.state.sessions() as db:
        uid = db.scalar(select(User.id).where(User.email == 'alice@example.com'))
        # Simulate classifications saved by the previous app version.
        for t in db.scalars(select(Transaction)):
            t.kind, t.category = 'review', 'Нужно уточнить'
        owner = db.scalar(select(Transaction).where(Transaction.user_id == uid, Transaction.description == OWN))
        owner.kind, owner.category, owner.manual = 'transfer', 'Между своими счетами', True
        db.add(CategoryRule(user_id=uid, description=OWN, direction=1, kind='transfer', category='Между своими счетами'))
        db.commit()
        assert classify_incoming_history(db, uid) == {'income': 2, 'own_transfer': 1}
        db.commit()
        assert classify_incoming_history(db, uid) == {}  # Safe to apply again.
    all_months = a.get('/api/dashboard?start=2026-01-01&end=2026-12-31').json()
    assert all_months['income_minor'] == 20000
    assert all_months['review_count'] == 1
    assert b.get('/api/dashboard?start=2026-01-01&end=2026-12-31').json()['income_minor'] == 0
    fresh = certificate([row(OTHER, '2026-11-01T10:00:00'), row(OWN_OTHER_BANK, '2026-11-01T11:00:00')])
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, fresh, b'%PDF-future')).status_code == 200
    fresh_items = a.get('/api/transactions?start=2026-11-01').json()['items']
    assert next(t for t in fresh_items if t['description'] == OTHER)['kind'] == 'income'
    assert next(t for t in fresh_items if t['description'] == OWN_OTHER_BANK)['kind'] == 'transfer'
    # Explicit own-transfer/refund decisions are stronger than defaults.
    target = next(t for t in fresh_items if t['description'] == OTHER)
    assert a.patch('/api/transactions/' + target['id'], headers=csrf,
                   json={'kind': 'transfer', 'category': 'Между своими счетами', 'remember': True}).status_code == 200
    later = certificate([row(OTHER, '2026-11-02T10:00:00')])
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, later, b'%PDF-later')).status_code == 200
    assert a.get('/api/transactions?start=2026-11-02').json()['items'][0]['kind'] == 'transfer'
