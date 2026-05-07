"""
agent.py — Ядро агента DriveVostoka
"""

import logging
import re

import anthropic

from database import get_history, get_profile, save_message
from tools import TOOL_SCHEMAS, execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — умный агент по подбору автомобилей из Кореи, работаешь в компании DriveVostoka (@DriveVostoka).
Никогда не называй себя Claude — ты «помощник DriveVostoka».

ОБЯЗАТЕЛЬНАЯ АНКЕТА КЛИЕНТА
Когда клиент обращается впервые — собирай параметры по одному вопросу за раз:
1. Марка/модель → «Какую марку и модель рассматриваете?»
2. Год → «С какого года выпуска ищем?»
3. Пробег → «Максимальный пробег?»
4. Объём двигателя → «Предпочтения по объёму двигателя?»
5. Цвет → «Есть предпочтения по цвету кузова?»

После получения всех пяти параметров — сразу вызывай search_and_calculate.
Если клиент говорит «любой» или «без разницы» — переходи к следующему вопросу.
Если несколько марок — передавай в makers как список: ["Kia", "Hyundai"].

СРАВНИТЕЛЬНАЯ ТАБЛИЦА
Когда находишь 2+ вариантов — форматируй как таблицу:
┌─────────────────────────────────────┐
│ 🥇 Вариант 1. Kia Sportage 2022     │
│ 🛣 45 000 км · ⚙️ 2.0л Бензин       │
│ 💰 2 850 000 ₽                      │
├─────────────────────────────────────┤
│ 🥈 Вариант 2. Hyundai Tucson 2021   │
│ 🛣 62 000 км · ⚙️ 2.0л Бензин       │
│ 💰 2 740 000 ₽                      │
└─────────────────────────────────────┘
Под таблицей — разбивка стоимости для лучшего варианта и ссылка на Encar.

ФОТОГРАФИИ АВТОМОБИЛЯ
Когда в результатах поиска есть непустой массив "photos" у первого варианта —
ОБЯЗАТЕЛЬНО добавляй в начало ответа:
[PHOTOS:url1||url2]
Используй URL из поля "photos" первого авто (до 2 штук).

РАСЧЁТ И ФОРМАТ ЦЕН
- Расчёт всегда ДО Владивостока
- Итоговую цену формулируй: «Итого под ключ в порту г.Владивосток»
- Числа с пробелами: 3 500 000 ₽
- Показывай 4 строки: цена авто с доставкой, пошлина, таможенный сбор, утилсбор

ВАЖНЫЕ ФАКТЫ РЫНКА (2025-2026)
- С 01.12.2025 утилизационный сбор вырос в 2-3 раза для авто 2+ литра
- Самые выгодные сегменты: авто до 2.0л и электромобили
- Срок доставки Корея → Владивосток: 30-45 дней

АДАПТАЦИЯ ПОД ЦЕЛЬ
• goal = "для себя" → акцент на комплектации и надёжности
• goal = "на перепродажу" → акцент на ликвидности и марже
• goal = "сравнить с рынком РФ" → сравнение с ценой на Авито/дилер

СТИЛЬ
- По-русски, дружелюбно, на «ты»
- Один вопрос за раз
- Если бюджет и тип уже в профиле — не спрашивай снова
- Когда готов к покупке — собери имя и телефон, вызови register_lead"""


PHOTOS_RE = re.compile(r'^\[PHOTOS:[^\]]+\]\s*', re.MULTILINE)


def _strip_photos_marker(text: str) -> str:
    return PHOTOS_RE.sub("", text).strip()


async def run_agent(
    chat_id: int,
    user_message: str,
    claude_client: anthropic.AsyncAnthropic,
    max_iterations: int = 6,
) -> str:
    save_message(chat_id, "user", user_message)

    profile = get_profile(chat_id)
    profile_context = ""
    if profile:
        parts = []
        if profile.get("budget_rub"):
            lbl = profile.get("budget_label") or f"{profile['budget_rub']:,.0f} ₽"
            parts.append(f"бюджет {lbl}")
        if profile.get("city"):
            parts.append(f"город {profile['city']}")
        if profile.get("preferred_maker"):
            parts.append(f"предпочитает {profile['preferred_maker']}")
        if profile.get("body_type"):
            parts.append(f"тип кузова: {profile['body_type']}")
        if profile.get("goal"):
            parts.append(f"цель: {profile['goal']}")
        if parts:
            profile_context = f"\n[Профиль клиента: {', '.join(parts)}]"

    messages = get_history(chat_id, limit=20)

    if profile_context and messages:
        messages[-1] = {
            "role": "user",
            "content": messages[-1]["content"] + profile_context
        }

    for iteration in range(max_iterations):
        response = await claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = _extract_text(response)
            save_message(chat_id, "assistant", _strip_photos_marker(text))
            return text

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                logger.info(f"[Agent] Инструмент: {block.name} | вход: {block.input}")

                try:
                    result = await execute_tool(
                        tool_name=block.name,
                        tool_input=block.input,
                        chat_id=chat_id,
                    )
                except Exception as e:
                    result = f"Ошибка выполнения инструмента: {e}"
                    logger.error(f"Tool error [{block.name}]: {e}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        break

    fallback = "Произошла ошибка. Попробуйте ещё раз или напишите менеджеру: @DriveVostoka"
    save_message(chat_id, "assistant", fallback)
    return fallback


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
