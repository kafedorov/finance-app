from dataclasses import asdict, replace

import pytest
from sqlalchemy import select

from backend.categorization import classify
from backend.database import Account, Snapshot
from backend.importers import yandex
from backend.importers.models import BalanceSnapshot, ParsedCertificate, Transaction
from backend.services import fingerprint
from test_app import clients, upload, confirm


def savings_pages():
    return ['''Яндекс Банк
Выписка по договору Исх. № test
Договор банковского вклада до востребования для физических лиц "Сейв"
В рамках Договора открыт счёт 42301810000000005555
Выписка по Договору за период с 01.11.2026 по 03.11.2026
Описание операции Дата операции МСК
Сумма в валюте
Договора
Входящий перевод СБП 01.11.2026 +1 000,00 ₽
Перевод между счетами одного клиента 02.11.2026 –100,00 ₽
Перевод между счетами одного клиента 02.11.2026 –100,00 ₽
Исходящий перевод СБП, Получатель,
Банк 02.11.2026 –50,00 ₽
Капитализация процентов 03.11.2026 +1,00 ₽
0,00 ₽Входящий остаток на 01.11.2026
Страница 1 из 2
Продолжение на следующей странице''', '''Исходящий остаток за 03.11.2026 751,00 ₽
+1 001,00 ₽
–250,00 ₽Итого списаний
Итого зачислений
Страница 2 из 2
С уважением, Яндекс Банк''']


def card():
    def tx(description, amount, stamp):
        return Transaction(stamp, stamp, amount, 'RUB', amount, 'RUB', description, '1111', 1)
    rows = (tx('Перевод между счетами одного клиента', 10000, '2026-11-02T10:00:00'),
            tx('Оплата товаров и услуг', -10000, '2026-11-02T10:01:00'),
            tx('Перевод между счетами одного клиента', 10000, '2026-11-02T11:00:00'),
            tx('Оплата товаров и услуг', -10000, '2026-11-02T11:01:00'))
    return ParsedCertificate('movement', (BalanceSnapshot(yandex.key('40817810000000001111'), '1111', '2026-11-03', 0, 'RUB'),), rows, bank='yandex')


def test_savings_totals_daily_balances_and_repeated_identical_rows():
    result = yandex.parse_pages(savings_pages())
    assert result.kind == 'movement' and result.account_kind == 'savings'
    assert len(result.transactions) == 5
    assert [s.amount_minor for s in result.snapshots] == [100000, 75000, 75100]
    assert [s.as_of for s in result.snapshots] == ['2026-11-01', '2026-11-02', '2026-11-03']
    assert fingerprint(asdict(result.transactions[1])) == fingerprint(asdict(result.transactions[2]))
    assert result.transactions[3].description == 'Исходящий перевод СБП, Получатель, Банк'
    assert all(t.card_last4 is None for t in result.transactions)
    assert classify(result.transactions[1].description, -10000)[1] == 'transfer'
    assert classify(result.transactions[3].description, -5000)[1] == 'review'
    assert classify(result.transactions[4].description, 100)[1] == 'income'


@pytest.mark.parametrize('before,after', [('751,00', '750,00'), ('–250,00', '–251,00'), ('03.11.2026 +1,00', '04.11.2026 +1,00')])
def test_savings_rejects_bad_balance_totals_or_dates(before, after):
    with pytest.raises(ValueError):
        yandex.parse_pages([p.replace(before, after) for p in savings_pages()])


@pytest.mark.parametrize('savings_first', [True, False])
def test_card_and_savings_import_order_does_not_double_expenses(clients, monkeypatch, savings_first):
    app, a, csrf, b, _ = clients
    savings = yandex.parse_pages(savings_pages())
    docs = [savings, card()] if savings_first else [card(), savings]
    for i, parsed in enumerate(docs):
        preview = upload(a, csrf, monkeypatch, parsed, f'%PDF-order-{i}'.encode())
        if parsed.account_kind == 'savings':
            assert len(preview['summary']['snapshots']) == 1
            assert preview['summary']['snapshots'][0]['amount_minor'] == 75100
            assert preview['summary']['history_points'] == 3
        assert confirm(a, csrf, preview).status_code == 200
    url = '/api/dashboard?start=2026-11-01&end=2026-11-30&bank=yandex'
    dashboard = a.get(url).json()
    assert dashboard['expenses_minor'] == 20000  # Two purchases, no top-ups.
    assert dashboard['income_minor'] == 100  # Only earned interest.
    assert dashboard['total_minor'] == 75100  # Savings plus the zero card balance.
    assert dashboard['transaction_count'] == 9
    account = next(x for x in dashboard['accounts'] if x['kind'] == 'savings')
    assert len(account['history']) == 3
    own = a.get('/api/transactions?account_id=' + account['id']).json()
    assert own['total'] == 5
    assert all(x['account_kind'] == 'savings' for x in own['items'])
    assert b.get('/api/transactions?account_id=' + account['id']).json()['total'] == 0
    external = next(t for t in own['items'] if 'Исходящий' in t['description'])
    assert a.patch('/api/transactions/' + external['id'], headers=csrf,
                   json={'kind': 'expense', 'category': 'Другое'}).status_code == 200
    assert a.get(url).json()['expenses_minor'] == 25000
    # Overlapping re-export: preserve the two identical transfers and manual category.
    repeated = upload(a, csrf, monkeypatch, savings, b'%PDF-overlap')
    assert repeated['summary']['duplicates'] == 5 and repeated['summary']['new'] == 0
    assert confirm(a, csrf, repeated).status_code == 200
    assert a.get(url).json()['expenses_minor'] == 25000
    assert a.get('/api/transactions?account_id=' + account['id']).json()['total'] == 5
    assert a.patch('/api/accounts/' + account['id'] + '/visibility', headers=csrf, json={'is_hidden': True}).status_code == 200
    assert a.get(url).json()['total_minor'] == 0
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, savings, b'%PDF-hidden')).status_code == 200
    assert a.get(url).json()['total_minor'] == 0
    assert a.patch('/api/accounts/' + account['id'] + '/visibility', headers=csrf, json={'is_hidden': False}).status_code == 200
    assert a.get(url).json()['expenses_minor'] == 25000


def test_balance_certificate_then_savings_same_account_and_latest_snapshot(clients, monkeypatch):
    app, a, csrf, _, _ = clients
    parsed = yandex.parse_pages(savings_pages())
    balance = replace(parsed, kind='balance', account_kind=None, transactions=(),
                      snapshots=(replace(parsed.snapshots[-1], as_of='2026-11-04', amount_minor=80000),))
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, balance, b'%PDF-balance-first')).status_code == 200
    assert confirm(a, csrf, upload(a, csrf, monkeypatch, parsed, b'%PDF-savings-next')).status_code == 200
    data = a.get('/api/dashboard').json()
    assert len(data['accounts']) == 1 and data['accounts'][0]['kind'] == 'savings'
    assert data['accounts'][0]['amount_minor'] == 80000
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(Account)))) == 1
        assert len(list(db.scalars(select(Snapshot)))) == 4
