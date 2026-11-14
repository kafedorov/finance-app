from io import BytesIO
from dataclasses import replace

from pypdf import PdfReader

from . import tbank, yandex

ADAPTERS = (tbank, yandex)


def supported_banks():
    return [{"id": adapter.BANK_ID, "name": adapter.BANK_NAME} for adapter in ADAPTERS]


def bank_name(bank_id):
    if not bank_id or bank_id == "unassigned":
        return "Банк не указан"
    return next((b["name"] for b in supported_banks() if b["id"] == bank_id), bank_id)


def parse_document(content: bytes):
    if not content.startswith(b"%PDF-"):
        raise ValueError("Нужен PDF-файл банковской справки.")
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("Справка защищена паролем. Нужен PDF без пароля.")
    if not 0 < len(reader.pages) <= 600:
        raise ValueError("Поддерживаются справки объемом до 600 страниц.")
    first = reader.pages[0].extract_text() or ""
    for adapter in ADAPTERS:
        if adapter.detect(first):
            result = adapter.parse_pages([first, *[p.extract_text() or "" for p in reader.pages[1:]]])
            return replace(result, bank=adapter.BANK_ID, adapter_version=adapter.ADAPTER_VERSION)
    raise ValueError("Формат пока не поддерживается. Доступны справки Т-Банка и Яндекс Банка: движения по картам, накопительному счету Яндекса и остатки по вкладам.")
