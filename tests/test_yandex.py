from dataclasses import asdict

import pytest

from backend.importers import yandex, registry
from backend.categorization import classify
from backend.services import fingerprint


def section(account=True, corrupt=False):
    rows=("Перенос денежных средств с ЭДС на банковский счёт\n20.09.2024\nв 12:09\n20.09.2024 +100,00 ₽ +100,00 ₽\n"
          "Оплата товаров и услуг MARKET\n13.11.2026\nв 10:00\n13.11.2026 *1234 –25,00 ₽ –25,00 ₽") if account else (
          "Входящий перевод СБП\n29.09.2023\nв 12:00\n29.09.2023 +100,00 ₽ +100,00 ₽\n"
          "Перенос денежных средств с ЭДС на банковский счёт\n20.09.2024\nв 12:09\n20.09.2024 –100,00 ₽ –100,00 ₽")
    start,end=('20.09.2024','13.11.2026') if account else ('29.09.2023','20.09.2024')
    balance='75,00' if account else '0,00'
    debit='25,01' if corrupt else ('25,00' if account else '100,00')
    return ("Яндекс Банк\nВыписка по договору Исх. № test\n"+
            ('В рамках Договора открыт счёт 40817810000000001234\n' if account else '')+
            f"Выписка по Договору за период с {start} по {end}\n"
            "Описание операции Дата и время\nСумма в валюте\nДоговора\n"+rows+
            f"\nВходящий остаток на {start} 0,00 ₽\nИсходящий остаток за {end} {balance} ₽\n"
            f"+100,00 ₽\n–{debit} ₽Всего расходных операций\nВсего приходных операций\nСтраница 1 из 1")


def test_composite_wallet_and_card_use_one_stable_account():
    combined=yandex.parse_pages(['Яндекс Банк\nФайл содержит две выписки',section(False),section()])
    modern=yandex.parse_pages([section()])
    assert len(combined.snapshots)==1 and len(combined.transactions)==4
    assert combined.snapshots==modern.snapshots
    assert combined.snapshots[0].amount_minor==7500
    assert combined.snapshots[0].as_of=='2026-11-13'
    assert combined.credits_minor==20000 and combined.debits_minor==12500
    assert combined.period_start=='2023-09-29'
    assert [fingerprint(asdict(t)) for t in combined.transactions[2:]]==[fingerprint(asdict(t)) for t in modern.transactions]


def test_bad_section_totals_and_truncated_statement_rejected():
    with pytest.raises(ValueError):yandex.parse_pages([section(corrupt=True)])
    with pytest.raises(ValueError):yandex.parse_pages([section().replace('Всего расходных операций','Неполный файл')])
    with pytest.raises(ValueError):yandex.parse_pages([section(False)])


def test_balance_and_zero_balance_certificates():
    for amount,cents in [('679 358,39',67935839),('0,00',0)]:
        result=yandex.parse_pages([f'''Яндекс Банк
Справка о доступном остатке
В рамках Договора открыт счёт 42304810000000001234
По состоянию на 14.11.2026 входящий остаток по
Договору составляет
{amount} ₽
Входящий остаток'''])
        assert result.kind=='balance' and not result.transactions
        assert result.snapshots[0].amount_minor==cents
        assert result.snapshots[0].balance_type=='opening'


def test_original_currency_and_card_are_preserved():
    result=yandex.parse_pages([section().replace('–25,00 ₽ –25,00 ₽','–100,00 ֏ –25,00 ₽')])
    t=result.transactions[-1]
    assert t.original_currency=='AMD' and t.original_amount_minor==-10000
    assert t.currency=='RUB' and t.amount_minor==-2500 and t.card_last4=='1234'


def test_internal_transfers_and_loan_payments_not_shopping():
    assert classify('Перенос денежных средств с ЭДС на банковский счёт',-10000)[1]=='transfer'
    assert classify('Перевод между счетами одного клиента',10000)[1]=='transfer'
    assert classify('Погашение основного долга по договору',-10000)[1]=='review'
    assert 'yandex' in {b['id'] for b in registry.supported_banks()}


def test_deposit_statement_is_balance_not_card():
    text = """Яндекс Банк
Выписка по договору Исх. № test
«Срочный вклад \"Сейв\"»
В рамках Договора открыт счёт 42304810000000001234
Выписка по Договору за период с 15.09.2026 по 13.11.2026
Описание операции Дата операции
МСК
Сумма в валюте
Договора
Перевод между счетами одного клиента 15.09.2026 +100,00 ₽
0,00 ₽Входящий остаток на 15.09.2026
Исходящий остаток за 13.11.2026 100,00 ₽
+100,00 ₽
0,00 ₽Итого списаний
Итого зачислений
Страница 1 из 1"""
    result = yandex.parse_pages([text])
    assert result.kind == 'balance' and not result.transactions
    assert result.snapshots[0].amount_minor == 10000
    assert result.snapshots[0].as_of == '2026-11-13'
    assert result.credits_minor == 10000 and result.debits_minor == 0
    with pytest.raises(ValueError):
        yandex.parse_pages([text.replace('Исходящий остаток за 13.11.2026 100,00','Исходящий остаток за 13.11.2026 99,00')])
