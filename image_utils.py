"""
image_utils.py — Загрузка и обрезка фотографий с Encar.com
Логотип Encar вшит в нижнюю полосу фотографии.
Обрезаем снизу ~14% высоты.
"""

import logging
from io import BytesIO
from typing import Optional

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

CROP_TOP    = 0.00
CROP_BOTTOM = 0.14
CROP_LEFT   = 0.03
CROP_RIGHT  = 0.03

_HEADERS = {
    "Referer": "https://www.encar.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


async def fetch_and_crop(url: str) -> Optional[bytes]:
    try:
        async with httpx.AsyncClient(timeout=12, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.content
    except Exception as e:
        logger.warning(f"[image_utils] Не удалось скачать {url}: {e}")
        return None

    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
        w, h = img.size

        left   = int(w * CROP_LEFT)
        right  = int(w * (1 - CROP_RIGHT))
        top    = int(h * CROP_TOP)
        bottom = int(h * (1 - CROP_BOTTOM))

        cropped = img.crop((left, top, right, bottom))

        buf = BytesIO()
        cropped.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"[image_utils] Ошибка обрезки {url}: {e}")
        return None


async def prepare_photos(urls: list[str], limit: int = 2) -> list[bytes]:
    results: list[bytes] = []
    for url in urls[:limit]:
        data = await fetch_and_crop(url)
        if data:
            results.append(data)
        if len(results) >= limit:
            break
    return results
