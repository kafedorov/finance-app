import re

EXPENSE_CATEGORIES = ["Продукты", "Кафе и рестораны", "Транспорт", "Здоровье", "Спорт", "Покупки", "Связь и подписки", "Комиссии", "Другое"]
KINDS = {"expense", "income", "transfer", "refund", "review"}


def requires_manual_review(bank: str, description: str, amount: int) -> bool:
    """T-Bank anonymous SBP receipts must be classified individually."""
    if bank != "tbank" or amount <= 0:
        return False
    d = " ".join(description.casefold().replace("ё", "е").split())
    return (d == "пополнение. система быстрых платежей"
            or d.startswith("пополнение через сбп.")
            or d == "перевод по сбп")


def transfer_phones(description: str) -> set[str]:
    """Normalize Russian sender phones without mistaking account numbers for phones."""
    values = re.findall(r"(?<!\d)(?:\+?7|8)(?:[\s()\-]*\d){10}(?!\d)", description)
    return {"7" + re.sub(r"\D", "", value)[1:] for value in values}


def named_incoming_transfer(description: str) -> bool:
    # Yandex reports sender + phone for personal SBP transfers. Card top-ups and
    # anonymous T-Bank receipts do not identify whether the sender is the owner.
    match = re.match(r"\s*Входящий перевод СБП,\s*([^,]+),", description, re.I)
    if not match:
        return False
    sender = match[1].strip()
    return bool(re.fullmatch(r"[А-ЯЁA-Zа-яёa-z][А-ЯЁA-Zа-яёa-z-]+(?:\s+[А-ЯЁA-Zа-яёa-z][А-ЯЁA-Zа-яёa-z.\-]*){1,5}", sender))


def classify(description: str, amount: int, own_phones: set[str] | None = None, *, bank: str | None = None) -> tuple[str, str]:
    d = description.casefold().replace("ё", "е")
    if "брокерск" in d or "иис" in d:
        return "Инвестиции", "transfer"
    if "погашение основного долга" in d:
        return "Нужно уточнить", "review"
    if "перевод себе" in d or "между счетами одного клиента" in d or "перенос денежных средств с эдс" in d:
        return "Между своими счетами", "transfer"
    if amount > 0 and "входящий перевод сбп" in d and transfer_phones(description).intersection(own_phones or ()):
        return "Между своими счетами", "transfer"
    if "возврат" in d and amount > 0:
        return "Возвраты", "refund"
    if "кэшбэк" in d or "кешбэк" in d or "процент" in d and amount > 0:
        return "Вознаграждения", "income"
    if amount > 0 and named_incoming_transfer(description):
        return "Переводы от людей", "income"
    if bank == "tbank" and amount > 0 and re.match(r"^(?:внутрибанковский\s+)?перевод с договора\s+\S", d):
        return "Доход", "income"
    if amount > 0 or "перевод" in d or "снятие наличных" in d:
        return "Нужно уточнить", "review"
    groups = [
        ("Комиссии", ["комисси", "плата за оповещ", "плата за обслуж"]),
        ("Продукты", ["lenta", "yandex lavka", "yandex.lavka", "pyaterochka", "perekrestok", "magnit", "dixy", "vkusvill", "vv_kkm", "продукт", "karavay", "ovoshchi"]),
        ("Кафе и рестораны", ["yandex.eda", "yandex eda", "cafe", "coffee", "kfc", "rostics", "rostics", "vkusno", "burger", "ресторан", "кофе", "dodopizza"]),
        ("Транспорт", ["transport", "scooter", "taxi", "metro", "yandex go", "такси", "самокат"]),
        ("Здоровье", ["apteka", "aptechn", "gorzdrav", "аптек", "clinic"]),
        ("Спорт", ["fitness", "ddx", "climb", "спорт"]),
        ("Связь и подписки", ["мтс", "tele2", "mts", "megafon", "beeline", "yandex plus", "подписк", "мобильн"]),
        ("Покупки", ["ozon", "wildberries", "wb.ru", "market"]),
    ]
    for category, words in groups:
        if any(w in d for w in words):
            return category, "expense"
    return "Другое", "expense"
