"""
tools.py — Инструменты агента (tool_use для Claude API)

Ключевые правила расчёта:
  - KRW курс: ЦБ РФ + 0.003 (≈ +3 руб. на каждые 1000 вон) — маржа компании
  - Расчёт всегда ДО Владивостока (shipping_city = 0)
  - Итоговая строка: «Итого под ключ в порту г.Владивосток»
"""

import json
from typing import Any

from calculator import CarSpec, calculate, estimate_max_car_price_krw
from currency import format_price, get_rates
from database import (
    add_to_watchlist, get_profile, save_lead as db_save_lead, save_profile
)
from encar import search_cars

# Наценка к курсу ЦБ: +3 рубля на каждые 1000 вон
KRW_MARKUP = 0.003


TOOL_SCHEMAS = [
    {
        "name": "search_and_calculate",
        "description": (
            "Ищет автомобили на Encar.com и рассчитывает полную стоимость "
            "в порту г. Владивосток для каждого варианта. "
            "Вызывай ТОЛЬКО после того как собрал от клиента: марку/модель, год, "
            "пробег, объём двигателя и цвет кузова."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_rub": {
                    "type": "number",
                    "description": "Бюджет клиента в рублях, итого до Владивостока"
                },
                "maker": {
                    "type": "string",
                    "description": "Одна марка авто по-русски или по-английски"
                },
                "makers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Несколько марок для сравнения"
                },
                "model": {
                    "type": "string",
                    "description": "Модель авто"
                },
                "year_from": {
                    "type": "integer",
                    "description": "Год выпуска от (например: 2021)"
                },
                "max_mileage": {
                    "type": "integer",
                    "description": "Максимальный пробег в км"
                },
                "displacement_max": {
                    "type": "integer",
                    "description": "Макс. объём двигателя в куб.см"
                },
                "color": {
                    "type": "string",
                    "description": "Цвет кузова по-русски"
                },
                "is_electric": {
                    "type": "boolean",
                    "description": "Электромобиль? По умолчанию false"
                },
            },
            "required": ["budget_rub"],
        },
    },
    {
        "name": "calculate_specific_car",
        "description": (
            "Точный расчёт стоимости конкретного автомобиля по его параметрам "
            "до порта г. Владивосток."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "price_krw": {"type": "integer"},
                "displacement_cc": {"type": "integer"},
                "power_hp": {"type": "integer"},
                "age_years": {"type": "number"},
                "is_electric": {"type": "boolean"},
            },
            "required": ["price_krw", "displacement_cc", "power_hp", "age_years"],
        },
    },
    {
        "name": "save_client_profile",
        "description": "Сохраняет предпочтения клиента в базу данных.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "integer"},
                "budget_rub": {"type": "number"},
                "city": {"type": "string"},
                "preferred_maker": {"type": "string"},
                "preferred_model": {"type": "string"},
                "body_type": {"type": "string"},
                "max_mileage": {"type": "integer"},
                "year_from": {"type": "integer"},
                "engine_type": {"type": "string"},
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "register_lead",
        "description": "Сохраняет заявку клиента на покупку автомобиля.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "integer"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "car_choice": {"type": "string"},
                "budget_rub": {"type": "number"},
                "city": {"type": "string"},
            },
            "required": ["chat_id", "name", "phone", "car_choice"],
        },
    },
    {
        "name": "add_watchlist",
        "description": "Добавляет автомобиль в список отслеживания.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "integer"},
                "maker": {"type": "string"},
                "model": {"type": "string"},
                "budget_rub": {"type": "number"},
                "city": {"type": "string"},
            },
            "required": ["chat_id", "maker", "budget_rub", "city"],
        },
    },
    {
        "name": "get_exchange_rates",
        "description": "Получает актуальные курсы валют (KRW/RUB, EUR/RUB) от ЦБ РФ.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


async def execute_tool(tool_name: str, tool_input: dict, chat_id: int) -> str:
    if tool_name == "search_and_calculate":
        return await _search_and_calculate(chat_id=chat_id, **tool_input)
    elif tool_name == "calculate_specific_car":
        return await _calculate_specific(**tool_input)
    elif tool_name == "save_client_profile":
        tool_input.pop("chat_id", None)
        save_profile(chat_id, **{k: v for k, v in tool_input.items() if v is not None})
        return "✅ Профиль клиента сохранён."
    elif tool_name == "register_lead":
        tool_input.setdefault("chat_id", chat_id)
        lead_id = db_save_lead(
            chat_id=chat_id,
            name=tool_input.get("name", ""),
            phone=tool_input.get("phone", ""),
            car_choice=tool_input.get("car_choice", ""),
            budget_rub=tool_input.get("budget_rub", 0),
            city=tool_input.get("city", ""),
        )
        return json.dumps({
            "status": "success",
            "lead_id": lead_id,
            "message": "Заявка принята. Менеджер свяжется в ближайшее время."
        }, ensure_ascii=False)
    elif tool_name == "add_watchlist":
        watch_id = add_to_watchlist(
            chat_id=chat_id,
            maker=tool_input.get("maker", ""),
            model=tool_input.get("model", ""),
            budget_rub=tool_input.get("budget_rub", 0),
            city=tool_input.get("city", ""),
        )
        return f"✅ Добавлено в список отслеживания (ID: {watch_id})."
    elif tool_name == "get_exchange_rates":
        krw_raw, eur, usd = await get_rates()
        krw = krw_raw + KRW_MARKUP
        return json.dumps({
            "KRW_RUB_CBR": round(krw_raw, 4),
            "KRW_RUB_used": round(krw, 4),
            "EUR_RUB": round(eur, 2),
            "USD_RUB": round(usd, 2),
            "note": "Курс KRW = ЦБ РФ + 0.003 (+3 руб. на 1000 вон)"
        }, ensure_ascii=False)
    return f"Неизвестный инструмент: {tool_name}"


async def _search_and_calculate(
    budget_rub: float,
    chat_id: int = 0,
    maker: str = None,
    makers: list = None,
    model: str = None,
    year_from: int = None,
    max_mileage: int = None,
    displacement_max: int = None,
    color: str = None,
    is_electric: bool = False,
    city: str = "владивосток",
) -> str:
    krw_raw, eur_rub, _ = await get_rates()
    krw_rub = krw_raw + KRW_MARKUP

    est_cc  = displacement_max or 1600
    est_age = 2.5 if (year_from and year_from >= 2022) else 4.0
    est_hp  = _hp_by_cc(est_cc, is_electric)

    max_krw = estimate_max_car_price_krw(
        budget_rub=budget_rub,
        displacement_cc=est_cc,
        age_years=est_age,
        power_hp=est_hp,
        city="владивосток",
        rate_krw_rub=krw_rub,
        rate_eur_rub=eur_rub,
        is_electric=is_electric,
    )
    min_krw = int(max_krw * 0.35)

    cars = await search_cars(
        price_max_krw=max_krw,
        price_min_krw=min_krw,
        maker=maker,
        makers=makers,
        model=model,
        year_from=year_from,
        max_mileage=max_mileage,
        max_displacement=displacement_max,
        color=color,
        limit=5,
    )

    if not cars:
        return json.dumps({
            "found": 0,
            "message": "Варианты не найдены. Рекомендую расширить критерии поиска.",
            "max_car_price_krw": max_krw,
            "max_car_price_rub": round(max_krw * krw_rub),
        }, ensure_ascii=False)

    results = []
    for car in cars:
        spec = CarSpec(
            price_krw=car.price_krw,
            displacement_cc=car.displacement_cc,
            power_hp=_hp_by_cc(car.displacement_cc, car.is_electric),
            age_years=car.age_years,
            is_electric=car.is_electric,
            city="владивосток",
        )
        cost = calculate(spec, krw_rub, eur_rub)
        fits_budget = cost.total <= budget_rub * 1.05

        results.append({
            "title": f"{car.maker} {car.model} {car.badge}",
            "year": f"{car.year}/{car.month:02d}",
            "mileage_km": car.mileage,
            "displacement_cc": car.displacement_cc,
            "fuel": car.fuel_ru,
            "color": car.color,
            "price_korea_rub": round(car.price_krw * krw_rub),
            "total_vladivostok_rub": round(cost.total),
            "label": "Итого под ключ в порту г.Владивосток",
            "fits_budget": fits_budget,
            "cost_breakdown": {k: round(v) for k, v in cost.as_dict().items()},
            "encar_link": car.encar_link(),
            "photos": car.photos[:2] if car.photos else [],
        })

    return json.dumps({
        "found": len(results),
        "budget_rub": budget_rub,
        "destination": "Порт г.Владивосток",
        "exchange_rate_krw_rub": round(krw_rub, 4),
        "exchange_rate_cbr": round(krw_raw, 4),
        "results": results,
    }, ensure_ascii=False, indent=2)


async def _calculate_specific(
    price_krw: int,
    displacement_cc: int,
    power_hp: int,
    age_years: float,
    is_electric: bool = False,
    city: str = "владивосток",
) -> str:
    krw_raw, eur_rub, _ = await get_rates()
    krw_rub = krw_raw + KRW_MARKUP

    spec = CarSpec(
        price_krw=price_krw,
        displacement_cc=displacement_cc,
        power_hp=power_hp,
        age_years=age_years,
        is_electric=is_electric,
        city="владивосток",
    )
    cost = calculate(spec, krw_rub, eur_rub)
    return json.dumps({
        "total_vladivostok_rub": round(cost.total),
        "label": "Итого под ключ в порту г.Владивосток",
        "breakdown": {k: round(v) for k, v in cost.as_dict().items()},
        "rates": {
            "KRW_RUB_used": round(krw_rub, 4),
            "KRW_RUB_CBR": round(krw_raw, 4),
            "EUR_RUB": round(eur_rub, 2),
        },
    }, ensure_ascii=False, indent=2)


def _hp_by_cc(cc: int, electric: bool = False) -> int:
    if electric:
        return 204
    thresholds = [(1000,75),(1400,100),(1600,123),(2000,150),
                  (2500,190),(3000,249),(3500,300),(9999,367)]
    for max_cc, hp in thresholds:
        if cc <= max_cc:
            return hp
    return 367
