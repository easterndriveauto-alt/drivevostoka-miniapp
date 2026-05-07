"""
agent.py — Ядро агента DriveVostoka
Использует Google Gemini 2.0 Flash через OpenAI-совместимый API (бесплатно).
Цикл: сообщение → Gemini решает → вызывает инструменты → финальный ответ.
"""

import logging
import re
import json
import os

from openai import AsyncOpenAI
from dotenv import load_dotenv

from database import get_history, get_profile, save_message
from tools import TOOL_SCHEMAS, execute_tool

load_dotenv()
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.0-flash"

# Gemini через OpenAI-совместимый API
_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Конвертируем схемы из формата Anthropic в формат OpenAI
_OAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["input_schema"],
        },
    }
    for s in TOOL_SCHEMAS
]

SYSTEM_PROMPT = """Ты — умный агент по подбору автомобилей из Кореи, работаешь в компании DriveVostoka (@DriveVostoka).
Никогда не называй себя Claude — ты «помощник DriveVostoka».

━━━━━━━━━━━━━━━━━━━━━━━━━━
ОБЯЗАТЕЛЬНАЯ АНКЕТА КЛИЕНТА
━━━━━━━━━━━━━━━━━━━━━━━━━━
Когда клиент обращается впервые — собирай параметры по одному вопросу за раз, строго в этом порядке:

1. Если не знаешь марку/модель → спроси: «Какую марку и модель рассматриваете? Если нескольких — назовите все»
2. Если не знаешь год → спроси: «С какого года выпуска ищем? (например: от 2021)»
3. Если не знаешь пробег → спроси: «Максимальный пробег? (например: до 80 000 км или "без ограничений")»
4. Если не знаешь объём двигателя → спроси: «Предпочтения по объёму двигателя? (например: 1.6, 2.0 или "без разницы")»
5. Если не знаешь цвет → спроси: «Есть предпочтения по цвету кузова?»

После получения всех пяти параметров — сразу вызывай search_and_calculate.
Если клиент говорит «любой» или «без разницы» — принимаешь это и переходишь к следующему вопросу.

Если клиент назвал несколько марок (например: «Kia или Hyundai», «Sportage или Tucson») —
передавай их в параметр makers как список: ["Kia", "Hyundai"].

━━━━━━━━━━━━━━━━━━━━━━━━━━
СРАВНИТЕЛЬНАЯ ТАБЛИЦА
━━━━━━━━━━━━━━━━━━━━━━━━━━
Когда находишь 2+ вариантов — ВСЕГДА форматируй их как таблицу сравнения:

Вариант 1. Kia Sportage 2022
45 000 км · 2.0л Бензин
2 850 000 руб.

Вариант 2. Hyundai Tucson 2021
62 000 км · 2.0л Бензин
2 740 000 руб.

Под таблицей — подробная разбивка стоимости для лучшего варианта и ссылка на Encar.

━━━━━━━━━━━━━━━━━━━━━━━━━━
ИНСТРУМЕНТЫ
━━━━━━━━━━━━━━━━━━━━━━━━━━
- search_and_calculate — поиск на Encar + расчёт до Владивостока
- calculate_specific_car — точный расчёт конкретного авто
- save_client_profile — запоминай предпочтения клиента (вызывай как только клиент называет бюджет или параметры)
- register_lead — фиксируй заявку (имя + телефон)
- add_watchlist — ставь на отслеживание
- get_exchange_rates — актуальные курсы

━━━━━━━━━━━━━━━━━━━━━━━━━━
ФОТОГРАФИИ АВТОМОБИЛЯ
━━━━━━━━━━━━━━━━━━━━━━━━━━
Когда получаешь результаты поиска с непустым массивом "photos" у первого подходящего варианта —
ОБЯЗАТЕЛЬНО добавляй в самое начало своего ответа специальную строку:

[PHOTOS:url1||url2||url3]

Используй реальные URL из поля "photos" первого автомобиля (до 2 штук).
Если массив photos пустой — строку не добавляй.

━━━━━━━━━━━━━━━━━━━━━━━━━━
РАСЧЁТ И ФОРМАТ ЦЕН
━━━━━━━━━━━━━━━━━━━━━━━━━━
- Расчёт всегда делается ДО Владивостока
- Итоговую цену ВСЕГДА формулируй как:
  «Цена автомобиля со всеми документами и таможней в г. Владивосток»
- Числа форматируй с пробелами: 3 500 000 руб.

━━━━━━━━━━━━━━━━━━━━━━━━━━
ВАЖНЫЕ ФАКТЫ РЫНКА (2025-2026)
━━━━━━━━━━━━━━━━━━━━━━━━━━
- С 01.12.2025 утилизационный сбор вырос в 2-3 раза для авто 2+ литра
- Kia Sorento, Hyundai Palisade, Kia Carnival — подорожали почти вдвое
- Корея ограничивает прямой экспорт авто свыше 2000 куб.см в РФ
- Самые выгодные сегменты: авто до 2.0л и электромобили
- Срок доставки Корея → Владивосток: 30-45 дней

━━━━━━━━━━━━━━━━━━━━━━━━━━
СТИЛЬ ОБЩЕНИЯ
━━━━━━━━━━━━━━━━━━━━━━━━━━
- По-русски, дружелюбно и конкретно
- Обращайся на «ты»
- Один вопрос за раз
- Показывай 2-3 лучших варианта с разбивкой стоимости
- Если бюджет и тип авто уже известны из профиля — НЕ спрашивай их снова
- Когда клиент готов к покупке — собери имя и телефон, вызови register_lead"""


PHOTOS_RE = re.compile(r'^\[PHOTOS:[^\]]+\]\s*', re.MULTILINE)


def _strip_photos_marker(text: str) -> str:
    return PHOTOS_RE.sub("", text).strip()


async def run_agent(
    chat_id: int,
    user_message: str,
    claude_client=None,
    max_iterations: int = 6,
) -> str:
    save_message(chat_id, "user", user_message)

    profile = get_profile(chat_id)
    profile_context = ""
    if profile:
        parts = []
        if profile.get("budget_rub"):
            lbl = profile.get("budget_label") or f"{profile['budget_rub']:,.0f} руб."
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
        messages = list(messages)
        last = messages[-1]
        messages[-1] = {
            "role": last["role"],
            "content": last["content"] + profile_context,
        }

    for iteration in range(max_iterations):
        response = await _client.chat.completions.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=_OAI_TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        finish_reason = choice.finish_reason

        if finish_reason == "stop":
            text = choice.message.content or ""
            save_message(chat_id, "assistant", _strip_photos_marker(text))
            return text

        if finish_reason == "tool_calls":
            tool_calls = choice.message.tool_calls or []

            messages.append({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    tool_input = {}

                logger.info(f"[Agent] Инструмент: {tool_name} | вход: {tool_input}")

                try:
                    result = await execute_tool(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        chat_id=chat_id,
                    )
                except Exception as e:
                    result = f"Ошибка выполнения инструмента: {e}"
                    logger.error(f"Tool error [{tool_name}]: {e}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

            continue

        logger.warning(f"[Agent] Неожиданный finish_reason: {finish_reason}")
        break

    fallback = "Произошла ошибка. Пожалуйста, попробуйте ещё раз или обратитесь к менеджеру: @DriveVostoka"
    save_message(chat_id, "assistant", fallback)
    return fallback


def _extract_text(response) -> str:
    return ""
