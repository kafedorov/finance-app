from dataclasses import replace
from datetime import date

from sqlalchemy import select

from backend.analytics import coverage_state, merge_intervals, month_shift
from backend.database import Account, Document, Transaction
from backend.importers.models import BalanceSnapshot
from test_app import clients, certificate, upload, confirm


def statement(rows, start='2026-10-01', end='2026-11-13', key=None, bank='tbank'):
    parsed=certificate(rows)
    snap=replace(parsed.snapshots[0],as_of=end,account_key=key or parsed.snapshots[0].account_key)
    return replace(parsed,bank=bank,period_start=start,period_end=end,snapshots=(snap,))


def row(description,day,amount,kind=None):
    return replace(certificate().transactions[0],description=description,occurred_at=day+'T12:00:00',posted_at=day+'T13:00:00',amount_minor=amount,original_amount_minor=amount)


def test_partial_month_equal_days_coverage_and_transfers(clients,monkeypatch):
    app,a,csrf,_,_=clients
    rows=[row('Оплата в PYATEROCHKA','2026-10-05',-10000),row('Оплата в PYATEROCHKA','2026-10-20',-80000),row('Оплата в PYATEROCHKA','2026-11-05',-30000),row('Перевод себе','2026-11-06',900000),row('Входящий перевод СБП, Анна Игоревна А., +7 900 000-00-02, Банк','2026-11-07',50000),row('Возврат покупки','2026-11-08',7000),row('Снятие наличных','2026-11-09',-40000)]
    assert confirm(a,csrf,upload(a,csrf,monkeypatch,statement(rows))).status_code==200
    response=a.get('/api/analytics?start=2026-11-01&end=2026-11-30')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['period']['end']=='2026-11-13'
    assert data['previous_period']=={'start':'2026-10-01','end':'2026-10-13'}
    assert data['current']['expenses_minor']==30000 and data['previous']['expenses_minor']==10000
    assert data['current']['income_minor']==50000 and data['current']['net_minor']==20000
    assert data['current']['refunds_minor']==7000 and data['current']['review_out_minor']==40000
    assert data['coverage']==data['previous_coverage']=='complete'
    category=next(c for c in data['categories'] if c['name']=='Продукты')
    assert category['change_minor']==20000 and category['change_pct']==200
    daily=a.get('/api/analytics?start=2026-11-01&end=2026-11-30&bucket=day').json()
    assert len(daily['points'])==13 and daily['points'][0]['coverage']=='complete'
    assert daily['pace'][-1]['current_minor']==30000
    assert daily['pace'][-1]['previous_minor']==10000
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(Transaction))))==len(rows)


def test_scope_matches_dashboard_and_does_not_leak_other_user(clients,monkeypatch):
    _,a,csrf,b,csrf2=clients
    for i,(key,bank,amount) in enumerate([('a','tbank',10000),('b','yandex',20000)]):
        parsed=statement([row('Оплата в PYATEROCHKA','2026-11-05',-amount)],key=key,bank=bank)
        assert confirm(a,csrf,upload(a,csrf,monkeypatch,parsed,f'%PDF-scope-{i}'.encode())).status_code==200
    accounts=a.get('/api/dashboard').json()['accounts']
    aid=next(x['id'] for x in accounts if x['bank']=='tbank')
    dashboard=a.get('/api/dashboard?start=2026-11-01&end=2026-11-30&account_id='+aid).json()
    assert dashboard['expenses_minor']==10000 and len(dashboard['accounts'])==1
    assert len(dashboard['available_accounts'])==2
    data=a.get('/api/analytics?start=2026-11-01&end=2026-11-30&account_id='+aid).json()
    assert data['current']['expenses_minor']==10000
    assert a.get('/api/analytics?start=2026-11-01&end=2026-11-30&bank=yandex').json()['current']['expenses_minor']==20000
    other=b.get('/api/analytics?start=2026-11-01&end=2026-11-30&account_id='+aid).json()
    assert other['current']['expenses_minor']==0 and not other['categories'] and not other['account_ids']
    assert a.get('/api/analytics?start=2026-11-01&end=2026-11-30&bank=yandex&account_id='+aid).json()['current']['expenses_minor']==0


def test_statement_gap_is_missing_not_zero_and_long_history_bounded(clients,monkeypatch):
    _,a,csrf,_,_=clients
    for i,(start,end) in enumerate([('2026-01-01','2026-01-31'),('2026-03-01','2026-03-31')]):
        parsed=statement([row('Оплата в PYATEROCHKA',start,-10000)],start,end)
        assert confirm(a,csrf,upload(a,csrf,monkeypatch,parsed,f'%PDF-gap-{i}'.encode())).status_code==200
    data=a.get('/api/analytics?start=2026-01-01&end=2026-03-31').json()
    feb=next(m for m in data['months'] if m['date']=='2026-02')
    assert feb['coverage']=='missing' and data['coverage']=='partial'
    long=a.get('/api/analytics?start=1900-01-01&end=2200-01-01&bucket=day').json()
    assert len(long['points'])<=180 and len(long['months'])<=24


def test_date_validation_calendar_and_coverage_helpers(clients):
    _,a,_,_,_=clients
    for suffix in ['start=bad&end=2026-11-01','start=2026-11-02&end=2026-11-01','start=2026-11-01&end=2026-11-30&bucket=second']:
        assert a.get('/api/analytics?'+suffix).status_code==422
    assert month_shift(date(2024,3,31),-1)==date(2024,2,29)
    assert merge_intervals([(date(2026,1,1),date(2026,1,2)),(date(2026,1,3),date(2026,1,5))])==[(date(2026,1,1),date(2026,1,5))]
    assert coverage_state({'a':[(date(2026,1,1),date(2026,1,5))],'b':[]},date(2026,1,1),date(2026,1,5))=='partial'


def test_stale_bank_marks_partial_without_hiding_newer_bank_operations(clients,monkeypatch):
    _,a,csrf,_,_=clients
    for i,(key,bank,end,day) in enumerate([('old','tbank','2026-11-05','2026-11-04'),('fresh','yandex','2026-11-13','2026-11-12')]):
        parsed=statement([row('Оплата в PYATEROCHKA',day,-10000)],'2026-11-01',end,key,bank)
        assert confirm(a,csrf,upload(a,csrf,monkeypatch,parsed,f'%PDF-stale-{i}'.encode())).status_code==200
    data=a.get('/api/analytics?start=2026-11-01&end=2026-11-30').json()
    assert data['period']['end']=='2026-11-13' and data['current']['expenses_minor']==20000
    assert data['coverage']=='partial'
