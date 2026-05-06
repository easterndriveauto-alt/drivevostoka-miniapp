"""
currency.py — Актуальные курсы валют через API Банка России (ЦБ РФ)
Обновляются раз в час, кешируются в памяти.
"""

import asyncio
import time
import xml.etree.ElementTree as ET
from typing import Tuple

import httpx

_cache: dict = {}
_CACHE_TTL = 3600  # 1 час


async def _fetch_cbr_rates() -> dict:
    """Загружает курсы ЦБ РФ (XML), возвращает словарь {CharCode: rate_rub}."""
    url = "https://www.cbr.ru/scripts/XML_daily.asp"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    rates = {}
    for valute in root.findall("Valute"):
        code = valute.findtext("CharCode")
        nominal = int(valute.findtext("Nominal", "1"))
        value_str = valute.findtext("Value", "0").replace(",", ".")
        rate = float(value_str) / nominal
        rates[code] = rate
    return rates


async def get_rates() -> Tuple[float, float, float]:
    """
    Возвращает (krw_rub, eur_rub, usd_rub).
    Данные кешируются на 1 час.
    """
    now = time.time()
    if "rates" in _cache and now - _cache.get("ts", 0) < _CACHE_TTL:
        r = _cache["rates"]
        return r["KRW"], r["EUR"], r["USD"]

    try:
        rates = await _fetch_cbr_rates()
        krw = rates.get("KRW", 0.085)
        eur = rates.get("EUR", 95.0)
        usd = rates.get("USD", 88.0)
        _cache["rates"] = {"KRW": krw, "EUR": eur, "USD": usd}
        _cache["ts"] = now
        return krw, eur, usd
    except Exception:
        return 0.085, 95.0, 88.0


async def krw_to_rub(amount_krw: int) -> float:
    krw, _, _ = await get_rates()
    return amount_krw * krw


def format_price(amount_rub: float) -> str:
    """Красиво форматирует сумму в рублях."""
    return f"{round(amount_rub):,} ₽".replace(",", " ")
