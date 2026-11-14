"""Yandex Bank: contract statement (including legacy wallet) and balance certificate."""
import hashlib
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from .models import BalanceSnapshot, ParsedCertificate, Transaction

BANK_ID = "yandex"
BANK_NAME = "Яндекс Банк"
ADAPTER_VERSION = "yandex-certificates-v3"
D = r"\d{2}\.\d{2}\.\d{4}"
M = r"\d[\d \xa0\u202f]*[,.]\d{2}"
SIGNED = rf"[+\-–−]{M}"
ROW = re.compile(rf"({D})\s+в\s+(\d{{2}}:\d{{2}})\s+({D})\s+(?:\*(\d{{4}})\s+)?({SIGNED})\s+(\S+)\s+({SIGNED})\s+(\S+)")
CURRENCIES = {"₽":"RUB", "RUB":"RUB", "€":"EUR", "EUR":"EUR", "$":"USD", "USD":"USD", "֏":"AMD", "AMD":"AMD"}


def date(value):
    return datetime.strptime(value, "%d.%m.%Y").date().isoformat()


def cents(value):
    value = re.sub(r"\s", "", value).replace(",", ".").replace("–", "-").replace("−", "-")
    return int(Decimal(value) * 100)


def key(account):
    return hashlib.sha256(f"{BANK_ID}:{account}".encode()).hexdigest()


def currency(value):
    if value not in CURRENCIES:
        raise ValueError("В справке Яндекс Банка встретилась неподдерживаемая валюта.")
    return CURRENCIES[value]


def detect(text):
    if not re.search(r"Яндекс\s+Банк", text, re.I):
        return None
    if "Справка о доступном остатке" in text:
        return "balance"
    if "Выписка по договору" in text and re.search(r"банковского вклада\s+до востребования", text, re.I):
        return "savings_statement"
    if "Выписка по договору" in text and "Срочный вклад" in text:
        return "deposit_statement"
    if "Выписка по договору" in text or "Файл содержит две выписки" in text:
        return "movement"
    return None


def fail(message):
    raise ValueError(f"Яндекс Банк: {message}. Импорт не выполнен.")


def parse_deposit_statement(pages, savings=False):
    text = "\n".join(pages)
    account = re.search(r"В рамках Договора открыт сч[её]т\s+(\d{20})", text)
    period = re.search(rf"Выписка по Договору за период с\s+({D})\s+по\s+({D})",text,re.I)
    opening = re.search(rf"Входящий остаток на\s+({D})\s+({M})\s+₽",text)
    if opening:
        opening_date,opening_amount=opening[1],cents(opening[2])
    else:
        opening = re.search(rf"({M})\s+₽\s*Входящий остаток на\s+({D})",text)
        if not opening:
            fail("не найден начальный остаток вклада")
        opening_date,opening_amount=opening[2],cents(opening[1])
    closing = re.search(rf"Исходящий остаток за\s+({D})\s+({M})\s+₽",text)
    totals = re.search(rf"(\+?{M})\s+₽\s+([–−-]?{M})\s+₽\s*Итого списаний\s+Итого зачислений",text)
    if not all([account,period,closing,totals]):
        fail("не найдены реквизиты, период или контрольные итоги выписки вклада")
    if date(opening_date)!=date(period[1]) or date(closing[1])!=date(period[2]):
        fail("даты остатков вклада не совпадают с периодом")
    transactions=[]
    row_pattern=re.compile(rf"({D})\s+({SIGNED})\s+(\S+)")
    for page_number,page in enumerate(pages,1):
        header=re.search(r"Сумма в валюте\s+Договора\s*\n",page)
        if not header:
            if savings and re.match(r"\s*Исходящий остаток за",page):
                continue  # The bank may put closing totals on a separate last page.
            fail("не найдена таблица движений вклада")
        body=re.split(rf"(?:^|\n)(?:{M}\s+₽\s*)?(?:Входящий остаток на|Исходящий остаток за|Страница\s+\d+)",page[header.end():])[0].strip()
        last=0
        for row in row_pattern.finditer(body):
            description=" ".join(body[last:row.start()].split())
            if not description or currency(row[3])!="RUB":
                fail("не распознана строка движения вклада")
            occurred=date(row[1])
            if not date(period[1]) <= occurred <= date(period[2]):
                fail("дата операции выходит за период выписки")
            amount=cents(row[2])
            transactions.append(Transaction(f"{occurred}T00:00:00",f"{occurred}T00:00:00",amount,"RUB",amount,"RUB",description,None,page_number))
            last=row.end()
        if body[last:].strip():
            fail("не все строки движения вклада распознаны")
    credits,debits=cents(totals[1]),abs(cents(totals[2]))
    if sum(t.amount_minor for t in transactions if t.amount_minor>0)!=credits or -sum(t.amount_minor for t in transactions if t.amount_minor<0)!=debits:
        fail("движения вклада не сходятся с итогами")
    if opening_amount+credits-debits!=cents(closing[2]):
        fail("не сходятся остатки и движения вклада")
    snapshot=BalanceSnapshot(key(account[1]),account[1][-4:],date(closing[1]),cents(closing[2]),"RUB","closing")
    snapshots=(snapshot,)
    if savings:
        # Reconstruct end-of-day balances from the checked opening balance.
        daily=defaultdict(int)
        for t in transactions:
            daily[t.occurred_at[:10]]+=t.amount_minor
        history=[];running=opening_amount
        for day,change in sorted(daily.items()):
            running+=change
            history.append(BalanceSnapshot(key(account[1]),account[1][-4:],day,running,"RUB","closing"))
        if not history or history[-1].as_of!=snapshot.as_of:
            history.append(snapshot)
        snapshots=tuple(history)
    # Fixed-term deposits remain balance-only. Savings have spendable movements.
    return ParsedCertificate("movement" if savings else "balance",snapshots,tuple(transactions) if savings else (),period_start=date(period[1]),period_end=date(period[2]),credits_minor=credits,debits_minor=debits,adapter_version=ADAPTER_VERSION,bank=BANK_ID,account_kind="savings" if savings else "deposit")


def parse_pages(pages):
    if not pages or not detect(pages[0]):
        fail("неизвестный формат справки")
    text = "\n".join(pages)
    if detect(pages[0]) == "deposit_statement":
        return parse_deposit_statement(pages)
    if detect(pages[0]) == "savings_statement":
        return parse_deposit_statement(pages,savings=True)
    if detect(pages[0]) == "balance":
        account = re.search(r"В рамках Договора открыт сч[её]т\s+(\d{20})", text)
        balance = re.search(rf"По состоянию на\s+({D})\s+входящий остаток по\s+Договору составляет\s+({M})\s+(\S+)", text)
        if not account or not balance:
            fail("не удалось определить счет, дату и остаток")
        snapshot = BalanceSnapshot(key(account[1]),account[1][-4:],date(balance[1]),cents(balance[2]),currency(balance[3]),"opening")
        return ParsedCertificate("balance",(snapshot,),adapter_version=ADAPTER_VERSION,bank=BANK_ID)

    # A composite wallet/bank statement has one continuing card history. Its
    # current bank account is also the stable identity used by future statements.
    accounts = set(re.findall(r"В рамках Договора открыт сч[её]т\s+(\d{20})", text))
    if len(accounts) != 1:
        fail("нужна выписка одного банковского счета, при необходимости вместе с историей кошелька")
    account = next(iter(accounts))
    sections=[]
    for page_number,page in enumerate(pages,1):
        if re.search(r"Выписка по договору\s+Исх\.",page,re.I):
            sections.append([])
        if sections:
            sections[-1].append((page_number,page))
    if not sections:
        fail("не найдены разделы выписки")
    transactions=[]; starts=[]; ends=[]; credits=debits=0; final_balance=None
    for section in sections:
        part="\n".join(p for _,p in section)
        period=re.search(rf"Выписка по Договору за период с\s+({D})\s+по\s+({D})",part,re.I)
        opening=re.search(rf"Входящий остаток на\s+({D})\s+({M})\s+₽",part)
        closing=re.search(rf"Исходящий остаток за\s+({D})\s+({M})\s+₽",part)
        totals=re.search(rf"\+({M})\s+₽\s+[–−-]({M})\s+₽\s*Всего расходных операций\s+Всего приходных операций",part)
        if not all([period,opening,closing,totals]):
            fail("не найдены период, начальный/конечный остаток или контрольные итоги раздела")
        starts.append(date(period[1]));ends.append(date(period[2]))
        if date(opening[1])!=starts[-1] or date(closing[1])!=ends[-1]:
            fail("даты остатков не совпадают с периодом")
        parsed=[]
        for page_number,page in section:
            header=re.search(r"Сумма в валюте\s+(?:Договора|ЭСП)\s*\n",page)
            if not header:
                fail(f"не найдена таблица на странице {page_number}")
            body=re.split(r"(?:^|\n)(?:Входящий остаток на|Исходящий остаток за|Страница\s+\d+)",page[header.end():])[0].strip()
            matches=list(ROW.finditer(body))
            candidates=re.findall(rf"{D}\s+в\s+\d{{2}}:\d{{2}}\s+{D}",body)
            if len(candidates)!=len(matches):
                fail(f"не все строки распознаны на странице {page_number}")
            last=0
            for row in matches:
                description=" ".join(body[last:row.start()].split())
                if not description:
                    fail(f"нет описания операции на странице {page_number}")
                parsed.append(Transaction(f"{date(row[1])}T{row[2]}:00",f"{date(row[3])}T00:00:00",cents(row[7]),currency(row[8]),cents(row[5]),currency(row[6]),description,row[4],page_number))
                last=row.end()
            if body[last:].strip():
                fail(f"осталась нераспознанная строка на странице {page_number}")
        cr,dr=cents(totals[1]),cents(totals[2])
        if sum(t.amount_minor for t in parsed if t.amount_minor>0)!=cr or -sum(t.amount_minor for t in parsed if t.amount_minor<0)!=dr:
            fail("суммы операций не совпадают с итогами банка")
        if cents(opening[2])+cr-dr!=cents(closing[2]):
            fail("не сходится равенство начального остатка, движений и конечного остатка")
        if any(t.currency!="RUB" for t in parsed):
            fail("итоги раздела поддерживаются только в рублях")
        transactions.extend(parsed);credits+=cr;debits+=dr
        if final_balance is None or date(closing[1])>=final_balance[0]:
            final_balance=(date(closing[1]),cents(closing[2]))
    snapshot=BalanceSnapshot(key(account),account[-4:],final_balance[0],final_balance[1],"RUB","closing")
    return ParsedCertificate("movement",(snapshot,),tuple(transactions),min(starts),max(ends),credits,debits,ADAPTER_VERSION,BANK_ID)
