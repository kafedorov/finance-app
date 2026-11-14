"""Read-only adapter for Snowball's public portfolio web endpoint.

This is the public web client's endpoint, not a documented API contract.
Keep isolated: a provider change must not affect bank data or old snapshots.
"""
import json
import re
from decimal import Decimal, ROUND_HALF_UP

import httpx

URL = re.compile(r"https://snowball-income\.com/public/portfolios/([a-z]{20})(?:#\w+)?/?$")
ENDPOINT = "https://snowball-income.com/extapi/api/public/stats"


def public_key(url: str) -> str:
    match = URL.fullmatch(url.strip())
    if not match:
        raise ValueError("Нужна публичная ссылка вида https://snowball-income.com/public/portfolios/…")
    return match[1]


def cents(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fetch_portfolio(url: str) -> tuple[int, dict]:
    key = public_key(url)
    with httpx.Client(timeout=35, follow_redirects=False) as client:
        response = client.post(ENDPOINT, headers={"Accept": "application/json", "X-Instance": "ru", "X-User-Locale": "ru-RU", "Accept-Language": "ru"}, json={"currency": "RUB", "portfolioId": key, "include": "common.summary"})
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("Слишком большой ответ Snowball")
        data = json.loads(response.text, parse_float=Decimal)
    stats = (data.get("common") or {}).get("overallStats") or {}
    if stats.get("currentCost") is None:
        raise ValueError("Snowball не вернул стоимость. Проверьте доступность портфеля и денежных показателей по публичной ссылке.")
    details = {"source": "snowball", "profit_minor": cents(stats.get("incomeTotal", 0)), "basis_minor": cents(stats.get("basis", 0)), "daily_minor": cents(stats.get("lastDayGainsAmount", 0)), "passive_year_minor": cents(stats.get("divsIncomeYear", 0)), "cash_in_minor": cents(stats.get("cashIn", 0)), "cash_out_minor": cents(stats.get("cashOut", 0))}
    # Preserve the provider's metric and label. XIRR is not a period return.
    annual = stats.get("annualReturnWithCash") if stats.get("basisFromCash") else stats.get("annualReturn")
    details["annual_return_pct"] = float(annual) if annual is not None else None
    details["return_label"] = "Среднегодовая доходность · XIRR"
    details["return_warning"] = stats.get("annualReturnWarning")
    return cents(stats["currentCost"]), details
