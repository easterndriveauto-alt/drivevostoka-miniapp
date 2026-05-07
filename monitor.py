"""
monitor.py — Автомониторинг Encar по watchlist клиентов
Запускается как фоновая задача вместе с ботом.
Каждые N часов проверяет новые авто и уведомляет клиентов.
"""

import asyncio
import json
import logging
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode

from calculator import CarSpec, calculate, estimate_max_car_price_krw
from currency import format_price, get_rates
from database import get_active_watchlist, update_watchlist_checked
from encar import search_cars
from tools import _hp_by_cc

logger = logging.getLogger(__name__)

# Интервал проверки в секундах (по умолчанию — каждые 6 часов)
CHECK_INTERVAL = 6 * 60 * 60


async def check_watchlist(bot: Bot):
    """
    Обходит весь активный watchlist.
    Для каждой записи ищет авто на Encar,
    если нашлись новые подходящие — отправляет уведомление клиенту.
    """
    watchlist = get_active_watchlist()
    if not watchlist:
        return

    logger.info(f"[Monitor] Проверяю watchlist: {len(watchlist)} записей")
    krw_rub, eur_rub, _ = await get_rates()

    for entry in watchlist:
        try:
            await _check_entry(bot, entry, krw_rub, eur_rub)
            update_watchlist_checked(entry["id"])
            await asyncio.sleep(2)  # пауза между запросами к Encar
        except Exception as e:
            logger.error(f"[Monitor] Ошибка для entry {entry['id']}: {e}")


async def _check_entry(bot: Bot, entry: dict, krw_rub: float, eur_rub: float):
    chat_id    = entry["chat_id"]
    budget_rub = entry["budget_rub"]
    city       = entry["city"] or "Москва"
    maker      = entry.get("maker")
    model      = entry.get("model")

    # Оцениваем максимальную цену авто в KRW
    max_krw = estimate_max_car_price_krw(
        budget_rub=budget_rub,
        displacement_cc=1600,
        age_years=3.0,
        power_hp=130,
        city=city,
        rate_krw_rub=krw_rub,
        rate_eur_rub=eur_rub,
    )
    min_krw = int(max_krw * 0.4)

    cars = await search_cars(
        price_max_krw=max_krw,
        price_min_krw=min_krw,
        maker=maker,
        model=model,
        limit=3,
    )

    if not cars:
        return

    # Формируем уведомление
    lines = [
        "🔔 <b>Новые варианты по вашему запросу!</b>\n",
    ]
    if maker or model:
        search_desc = f"{maker or ''} {model or ''}".strip()
        lines[0] = f"🔔 <b>Новые варианты: {search_desc}</b>\n"

    for i, car in enumerate(cars[:2], 1):
        spec = CarSpec(
            price_krw=car.price_krw,
            displacement_cc=car.displacement_cc,
            power_hp=_hp_by_cc(car.displacement_cc, car.is_electric),
            age_years=car.age_years,
            is_electric=car.is_electric,
            city=city,
        )
        cost = calculate(spec, krw_rub, eur_rub)
        fits = cost.total <= budget_rub * 1.05
        icon = "✅" if fits else "⚠️"

        lines.append(
            f"{icon} <b>{car.maker} {car.model} {car.badge}</b>\n"
            f"📅 {car.year}/{car.month:02d} · "
            f"🛣 {car.mileage:,} км · "
            f"⚙️ {car.displacement_cc} куб.см {car.fuel_ru}\n"
            f"💰 Под ключ ({city}): <b>{format_price(cost.total)}</b>\n"
            f"🔗 <a href='{car.encar_link()}'>Смотреть на Encar</a>\n"
        )

    lines.append(
        "💬 Напишите мне чтобы узнать подробнее или оставить заявку."
    )

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    logger.info(f"[Monitor] Уведомление отправлено → chat_id={chat_id}")


async def run_monitor(bot: Bot):
    """
    Бесконечный цикл мониторинга.
    Запускается как asyncio-задача параллельно с ботом.
    """
    logger.info(f"[Monitor] Запущен. Интервал проверки: {CHECK_INTERVAL // 3600} ч")

    # Небольшая задержка при старте чтобы бот успел инициализироваться
    await asyncio.sleep(30)

    while True:
        try:
            await check_watchlist(bot)
        except Exception as e:
            logger.error(f"[Monitor] Критическая ошибка: {e}")

        logger.info(f"[Monitor] Следующая проверка через {CHECK_INTERVAL // 3600} ч")
        await asyncio.sleep(CHECK_INTERVAL)
