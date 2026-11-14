from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend import main, snowball
from backend.database import Account, Document, Snapshot, Transaction, User
from backend.importers.tbank import BalanceSnapshot, ParsedCertificate, Transaction as ParsedTransaction, account_key, parse_pages
from backend.services import now_iso


def certificate(rows=None, balance=10000, kind="movement"):
    rows = rows if rows is not None else [ParsedTransaction("2026-10-12T12:30:00", "2026-10-12T13:00:00", -10000, "RUB", -10000, "RUB", "Оплата в PYATEROCHKA", "1111", 1)]
    return ParsedCertificate(kind, (BalanceSnapshot(account_key("40817810000000001111"), "1111", "2026-10-19", balance, "RUB"),), tuple(rows), "2026-10-01", "2026-10-19", sum(t.amount_minor for t in rows if t.amount_minor>0), -sum(t.amount_minor for t in rows if t.amount_minor<0))


@pytest.fixture
def clients(tmp_path):
    app=main.create_app(f"sqlite:///{(tmp_path/'test.sqlite3').as_posix()}", production=False)
    first=TestClient(app)
    setup=first.post('/api/setup',json={'name':'Alice','email':'alice@example.com','password':'abc123'})
    assert setup.status_code==200
    csrf={'X-CSRF-Token':setup.json()['csrf']}
    with app.state.sessions() as db:
        db.add(User(name='Bob',email='bob@example.com',password_hash=main.PASSWORDS.hash('bob-password-123'),created_at=now_iso()))
        db.commit()
    second=TestClient(app)
    login=second.post('/api/login',json={'email':'bob@example.com','password':'bob-password-123'})
    csrf2={'X-CSRF-Token':login.json()['csrf']}
    yield app,first,csrf,second,csrf2
    first.close();second.close();app.state.engine.dispose()


def upload(client,csrf,monkeypatch,parsed=None,content=b'%PDF-test-1'):
    monkeypatch.setattr(main,'parse_document',lambda _:parsed or certificate())
    response=client.post('/api/imports/preview',content=content,headers={**csrf,'Content-Type':'application/pdf','X-Filename':'test.pdf'})
    assert response.status_code==200,response.text
    return response.json()


def confirm(client,csrf,preview):
    return client.post(f"/api/imports/{preview['id']}/confirm",headers=csrf)


def test_private_auth_csrf_and_origins(clients):
    app,a,csrf,b,csrf2=clients
    public=TestClient(app)
    assert public.get('/api/dashboard').status_code==401
    assert a.post('/api/logout').status_code==403
    assert a.post('/api/logout',headers={**csrf,'Origin':'https://attacker.invalid'}).status_code==403
    assert a.post('/api/setup',json={'name':'X','email':'x@example.com','password':'test-password-123'}).status_code==403
    assert a.get('/api/dashboard').headers['cache-control']=='no-store'
    assert a.get('/.local/finance.sqlite3').status_code==404
    assert 'httponly' in a.post('/api/login',json={'email':'alice@example.com','password':'abc123'}).headers['set-cookie'].lower()
    public.close()


def test_import_preview_atomicity_and_repeat(clients,monkeypatch):
    _,a,csrf,_,_=clients
    preview=upload(a,csrf,monkeypatch)
    assert preview['summary']['new']==1
    assert a.get('/api/transactions').json()['total']==0
    assert confirm(a,csrf,preview).json()['summary']['added']==1
    assert a.get('/api/transactions').json()['total']==1
    again=upload(a,csrf,monkeypatch)
    assert again['already_imported']
    assert confirm(a,csrf,preview).json()['already_imported']
    assert a.get('/api/transactions').json()['total']==1


def test_overlap_preserves_multiplicity_and_settled_time(clients,monkeypatch):
    _,a,csrf,_,_=clients
    parsed=certificate()
    assert confirm(a,csrf,upload(a,csrf,monkeypatch,parsed)).status_code==200
    duplicated=replace(parsed,transactions=(parsed.transactions[0],parsed.transactions[0]),debits_minor=20000)
    preview=upload(a,csrf,monkeypatch,duplicated,b'%PDF-test-2')
    assert preview['summary']['duplicates']==1
    assert preview['summary']['new']==1
    assert confirm(a,csrf,preview).status_code==200
    settled=replace(parsed.transactions[0],posted_at='2026-10-13T04:00:00')
    preview=upload(a,csrf,monkeypatch,replace(duplicated,transactions=(settled,settled)),b'%PDF-test-3')
    assert preview['summary']['new']==0
    assert preview['summary']['duplicates']==2
    assert confirm(a,csrf,preview).status_code==200
    assert a.get('/api/transactions').json()['total']==2


def test_changed_description_blocks_overlap(clients,monkeypatch):
    _,a,csrf,_,_=clients
    original=certificate()
    confirm(a,csrf,upload(a,csrf,monkeypatch,original))
    changed=replace(original,transactions=(replace(original.transactions[0],description='Другое описание'),))
    preview=upload(a,csrf,monkeypatch,changed,b'%PDF-changed')
    assert preview['summary']['ambiguous']==1
    assert confirm(a,csrf,preview).status_code==409
    assert a.get('/api/transactions').json()['total']==1


def test_ownership_all_routes_and_exports(clients,monkeypatch):
    _,a,csrf,b,csrf2=clients
    preview=upload(a,csrf,monkeypatch)
    assert confirm(b,csrf2,preview).status_code==404
    confirm(a,csrf,preview)
    t=a.get('/api/transactions').json()['items'][0]
    assert b.get('/api/transactions').json()['total']==0
    assert b.get('/api/dashboard').json()['accounts']==[]
    assert b.patch('/api/transactions/'+t['id'],headers=csrf2,json={'category':'Покупки','kind':'expense','remember':True}).status_code==404
    assert b.get('/api/export').json()['transactions']==[]
    assert b.post('/api/portfolios/'+t['account_id']+'/refresh',headers=csrf2).status_code==404
    own=upload(b,csrf2,monkeypatch)
    assert not own.get('already_imported')
    assert confirm(b,csrf2,own).status_code==200
    assert b.get('/api/transactions').json()['total']==1


def test_category_rules_apply_to_same_sign_only(clients,monkeypatch):
    _,a,csrf,_,_=clients
    original=certificate()
    confirm(a,csrf,upload(a,csrf,monkeypatch,original))
    t=a.get('/api/transactions').json()['items'][0]
    result=a.patch('/api/transactions/'+t['id'],headers=csrf,json={'category':'Покупки','kind':'expense','remember':True})
    assert result.status_code==200
    next_tx=replace(original.transactions[0],occurred_at='2026-10-13T12:30:00')
    refund=replace(next_tx,amount_minor=10000,original_amount_minor=10000,occurred_at='2026-10-14T12:30:00')
    confirm(a,csrf,upload(a,csrf,monkeypatch,replace(original,transactions=(next_tx,refund)),b'%PDF-new'))
    items=a.get('/api/transactions').json()['items']
    assert next(t for t in items if t['amount_minor']>0)['kind']=='review'
    assert all(t['category']=='Покупки' for t in items if t['amount_minor']<0)


def test_transfers_do_not_inflate_spending(clients,monkeypatch):
    _,a,csrf,_,_=clients
    original=certificate().transactions[0]
    rows=[original,replace(original,description='Пополнение брокерского счета',amount_minor=-100000,occurred_at='2026-10-13T12:30:00'),replace(original,description='Пополнение. Система быстрых платежей',amount_minor=110000,occurred_at='2026-10-14T12:30:00')]
    confirm(a,csrf,upload(a,csrf,monkeypatch,certificate(rows)))
    data=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31').json()
    assert data['expenses_minor']==10000
    assert data['income_minor']==0
    assert data['review_count']==1


def test_deposit_old_snapshots_do_not_replace_latest(clients,monkeypatch):
    _,a,csrf,_,_=clients
    first=certificate([],balance=500000,kind='balance')
    confirm(a,csrf,upload(a,csrf,monkeypatch,first))
    old=replace(first,snapshots=(replace(first.snapshots[0],as_of='2026-10-01',amount_minor=400000),))
    confirm(a,csrf,upload(a,csrf,monkeypatch,old,b'%PDF-old'))
    account=a.get('/api/dashboard').json()['accounts'][0]
    assert account['amount_minor']==500000
    assert account['change_minor']==100000
    assert len(account['history'])==2


def test_snowball_whitelist_and_stale_fallback(clients,monkeypatch):
    app,a,csrf,_,_=clients
    monkeypatch.setattr(snowball,'fetch_portfolio',lambda _: (1234500,{'profit_minor':234500,'annual_return_pct':9.8}))
    assert a.post('/api/portfolios',headers=csrf,json={'url':'http://127.0.0.1/internal','kind':'broker'}).status_code==422
    result=a.post('/api/portfolios',headers=csrf,json={'url':'https://snowball-income.com/public/portfolios/abcdefghijklmnopqrst','kind':'broker'})
    assert result.status_code==200,result.text
    account_id=result.json()['id']
    with app.state.sessions() as db:
        account=db.get(Account,account_id);account.last_attempt=0;db.commit()
    def failed(_): raise ValueError('provider unavailable')
    monkeypatch.setattr(snowball,'fetch_portfolio',failed)
    assert a.post('/api/portfolios/'+account_id+'/refresh',headers=csrf).status_code==502
    data=a.get('/api/dashboard').json()['accounts'][0]
    assert data['amount_minor']==1234500
    assert data['last_error']


def test_bank_parser_control_totals_and_original_currency():
    text='''АКЦИОНЕРНОЕ ОБЩЕСТВО «ТБАНК»
Справка о движении средств
Номер лицевого счета: 40817810000000001111
Сумма доступного остатка на 19.10.2026: 900.00 ₽
Движение средств за период с 01.10.2026 по 19.10.2026
12.10.2026
12:30
12.10.2026
13:00
-1.00 € -100.00 ₽ Оплата в TEST
1111
11.10.2026
12:30
11.10.2026
13:00
+1 000.00 ₽ +1 000.00 ₽ Перевод себе
1111
1 000,00 ₽Пополнения:
100,00 ₽Расходы:
АО «ТБанк» универсальная лицензия'''
    parsed=parse_pages([text])
    assert len(parsed.transactions)==2
    assert parsed.transactions[0].original_currency=='EUR'
    assert parsed.transactions[0].amount_minor==-10000
    assert parsed.snapshots[0].amount_minor==90000
    with pytest.raises(ValueError):parse_pages([text.replace('100,00 ₽Расходы:','100,01 ₽Расходы:')])


def test_acknowledge_only_changes_notification_and_preserves_new_reviews(clients,monkeypatch):
    _,a,csrf,b,csrf2=clients
    row=replace(certificate().transactions[0],description='Внешний перевод по номеру телефона')
    parsed=certificate([row])
    confirm(a,csrf,upload(a,csrf,monkeypatch,parsed))
    confirm(b,csrf2,upload(b,csrf2,monkeypatch,parsed))
    before=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31').json()
    assert before['all_review_count']==1
    assert a.post('/api/reviews/acknowledge',headers=csrf).json()['acknowledged']==1
    after=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31').json()
    assert after['all_review_count']==0 and after['review_count']==0
    assert after['review_total_count']==1
    assert after['review_out_minor']==before['review_out_minor']
    assert after['expenses_minor']==before['expenses_minor']
    assert a.get('/api/transactions?kind=review').json()['total']==1
    assert b.get('/api/dashboard').json()['all_review_count']==1
    # A changed PDF containing the same rows must not revive acknowledged ones.
    confirm(a,csrf,upload(a,csrf,monkeypatch,parsed,b'%PDF-overlap'))
    assert a.get('/api/dashboard').json()['all_review_count']==0
    next_row=replace(row,occurred_at='2026-10-13T12:30:00')
    confirm(a,csrf,upload(a,csrf,monkeypatch,certificate([row,next_row]),b'%PDF-next-week'))
    assert a.get('/api/dashboard').json()['all_review_count']==1


def test_hide_restore_deposits_and_reimport_preserve_history(clients,monkeypatch):
    app,a,csrf,b,csrf2=clients
    parsed=certificate([],balance=500000,kind='balance')
    cny=BalanceSnapshot(account_key('42306156000000002222'),'2222','2026-10-19',0,'CNY')
    parsed=replace(parsed,snapshots=(*parsed.snapshots,cny))
    confirm(a,csrf,upload(a,csrf,monkeypatch,parsed))
    accounts=a.get('/api/dashboard').json()['accounts']
    cny_account=next(t for t in accounts if t['currency']=='CNY')
    rub_account=next(t for t in accounts if t['currency']=='RUB')
    path='/api/accounts/'+cny_account['id']+'/visibility'
    assert b.patch(path,headers=csrf2,json={'is_hidden':True}).status_code==404
    assert a.patch(path,headers=csrf,json={'is_hidden':True}).status_code==200
    data=a.get('/api/dashboard').json()
    assert len(data['accounts'])==1 and len(data['hidden_accounts'])==1
    assert data['total_minor']==500000
    confirm(a,csrf,upload(a,csrf,monkeypatch,parsed,b'%PDF-new-balance'))
    assert len(a.get('/api/dashboard').json()['hidden_accounts'])==1
    exported=a.get('/api/export').json()
    assert len(exported['accounts'])==2 and len(exported['snapshots'])==2
    assert a.patch(path,headers=csrf,json={'is_hidden':False}).status_code==200
    assert len(a.get('/api/dashboard').json()['accounts'])==2
    assert a.patch('/api/accounts/'+rub_account['id']+'/visibility',headers=csrf,json={'is_hidden':True}).status_code==200
    assert a.get('/api/dashboard').json()['total_minor']==0
    with app.state.sessions() as db:
        assert db.query(Snapshot).count()==2


def test_bank_filter_scopes_accounts_transactions_charts_and_badges(clients,monkeypatch):
    _,a,csrf,b,_=clients
    original=certificate()
    confirm(a,csrf,upload(a,csrf,monkeypatch,original))
    other_row=replace(original.transactions[0],amount_minor=-20000,original_amount_minor=-20000)
    other=replace(certificate([other_row],balance=25000),bank='bank_b',adapter_version='bank-b-v1')
    confirm(a,csrf,upload(a,csrf,monkeypatch,other,b'%PDF-other-bank'))
    all_data=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31').json()
    filtered=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31&bank=bank_b').json()
    assert all_data['total_minor']==35000 and all_data['expenses_minor']==30000
    assert filtered['total_minor']==25000 and filtered['expenses_minor']==20000
    assert len(filtered['accounts'])==1
    assert sum(p['amount_minor'] for p in filtered['monthly'])==20000
    assert {v['id'] for v in all_data['banks']}=={'tbank','bank_b'}
    assert a.get('/api/transactions?bank=bank_b').json()['total']==1
    assert b.get('/api/transactions?bank=bank_b').json()['total']==0
    assert b.get('/api/dashboard').json()['banks']==[]
    monkeypatch.setattr(snowball,'fetch_portfolio',lambda _: (50000,{}))
    r=a.post('/api/portfolios',headers=csrf,json={'url':'https://snowball-income.com/public/portfolios/abcdefghijklmnopqrst','kind':'broker','institution':'bank_b'})
    assert r.status_code==200
    assert a.get('/api/dashboard?bank=bank_b').json()['total_minor']==75000
    assert a.get('/api/dashboard?bank=tbank').json()['total_minor']==10000


def test_acknowledge_respects_selected_bank(clients,monkeypatch):
    _,a,csrf,_,_=clients
    row=replace(certificate().transactions[0],description='Перевод по номеру телефона')
    confirm(a,csrf,upload(a,csrf,monkeypatch,certificate([row])))
    confirm(a,csrf,upload(a,csrf,monkeypatch,replace(certificate([row]),bank='bank_b'),b'%PDF-b-review'))
    assert a.post('/api/reviews/acknowledge?bank=tbank',headers=csrf).json()['acknowledged']==1
    assert a.get('/api/dashboard?bank=tbank').json()['all_review_count']==0
    assert a.get('/api/dashboard?bank=bank_b').json()['all_review_count']==1


def test_v1_migration_preserves_data_and_creates_backup(tmp_path):
    import sqlite3
    from sqlalchemy import inspect,text
    from backend.database import initialize,make_database
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE schema_version(version INTEGER PRIMARY KEY);
        INSERT INTO schema_version VALUES(1);
        CREATE TABLE accounts(id TEXT PRIMARY KEY,user_id TEXT,bank TEXT);
        INSERT INTO accounts VALUES('a','u','tbank'),('b','u','snowball');
        CREATE TABLE transactions(id TEXT PRIMARY KEY,kind TEXT);
        INSERT INTO transactions VALUES('t','review');
        ''')
    engine,_=make_database('sqlite:///'+path.as_posix())
    initialize(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version FROM schema_version')).scalar()==3
        assert connection.execute(text("SELECT institution FROM accounts WHERE id='b'")).scalar()=='tbank'
        assert connection.execute(text("SELECT is_hidden FROM accounts WHERE id='a'")).scalar()==0
        assert connection.execute(text("SELECT kind,review_acknowledged FROM transactions WHERE id='t'")).one()==('review',0)
    initialize(engine)
    assert len(list((tmp_path/'backups').glob('before-v2-*.sqlite3')))==1
    engine.dispose()


def test_new_adapter_metadata_overrides_legacy_model_defaults(monkeypatch):
    from types import SimpleNamespace
    from backend.importers import registry
    adapter=SimpleNamespace(BANK_ID='bank_b',BANK_NAME='Банк Б',ADAPTER_VERSION='bank-b-v1',detect=lambda _:True,parse_pages=lambda _:certificate())
    reader=SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda:'Second bank report')])
    monkeypatch.setattr(registry,'ADAPTERS',(adapter,))
    monkeypatch.setattr(registry,'PdfReader',lambda _:reader)
    result=registry.parse_document(b'%PDF-test')
    assert result.bank=='bank_b' and result.adapter_version=='bank-b-v1'
    assert registry.supported_banks()==[{'id':'bank_b','name':'Банк Б'}]


def test_custom_rent_category_reclassifies_cash_and_updates_analytics(clients,monkeypatch):
    _,a,csrf,_,_=clients
    cash=replace(certificate().transactions[0],description='Снятие наличных',amount_minor=-5000000,original_amount_minor=-5000000)
    confirm(a,csrf,upload(a,csrf,monkeypatch,certificate([cash])))
    t=a.get('/api/transactions').json()['items'][0]
    assert t['kind']=='review'
    created=a.post('/api/categories',headers=csrf,json={'name':'  Оплата   квартиры  '})
    assert created.status_code==200
    assert created.json()['name']=='Оплата квартиры'
    result=a.patch('/api/transactions/'+t['id'],headers=csrf,json={'kind':'expense','category':'Оплата квартиры'})
    assert result.status_code==200
    data=a.get('/api/dashboard?start=2026-10-01&end=2026-10-31').json()
    assert data['expenses_minor']==5000000
    assert data['categories']==[{'name':'Оплата квартиры','amount_minor':5000000}]
    assert 'Оплата квартиры' in data['expense_categories']
    assert a.get('/api/transactions?category=Оплата квартиры').json()['total']==1
    # Reimport preserves the user's category; an unrelated withdrawal stays review.
    next_cash=replace(cash,occurred_at='2026-10-13T12:30:00')
    confirm(a,csrf,upload(a,csrf,monkeypatch,certificate([cash,next_cash]),b'%PDF-new-cash'))
    items=a.get('/api/transactions').json()['items']
    assert sum(t['kind']=='expense' for t in items)==1
    assert sum(t['kind']=='review' for t in items)==1
    assert 'Оплата квартиры' in a.get('/api/export').json()['custom_categories']


def test_custom_category_names_are_private_and_validated(clients):
    _,a,csrf,b,csrf2=clients
    assert a.post('/api/categories',headers=csrf,json={'name':'   '}).status_code==422
    assert a.post('/api/categories',json={'name':'Квартира'}).status_code==403
    assert a.post('/api/categories',headers=csrf,json={'name':'Квартира'}).status_code==200
    duplicate=a.post('/api/categories',headers=csrf,json={'name':'квартира'})
    assert duplicate.json()['name']=='Квартира'
    assert a.get('/api/categories').json()['categories'].count('Квартира')==1
    assert 'Квартира' not in b.get('/api/categories').json()['categories']
    assert 'Квартира' not in b.get('/api/export').json()['custom_categories']
    assert b.post('/api/categories',headers=csrf2,json={'name':'Квартира'}).status_code==200
