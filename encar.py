"""
encar.py — Клиент для поиска автомобилей на Encar.com
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import httpx

MAKER_MAP = {
    "hyundai": "현대", "хендай": "현대", "хундай": "현대", "хёндай": "현대",
    "kia": "기아", "киа": "기아",
    "genesis": "제네시스", "дженесис": "제네시스",
    "ssangyong": "쌍용", "ссангйонг": "쌍용",
    "chevrolet": "쉐보레", "шевроле": "쉐보레",
    "renault": "르노", "рено": "르노",
    "bmw": "BMW", "бмв": "BMW",
    "mercedes": "벤츠", "мерседес": "벤츠",
    "audi": "아우디", "ауди": "아우디",
    "volkswagen": "폭스바겐", "фольксваген": "폭스바겐",
    "toyota": "도요타", "тойота": "도요타",
    "lexus": "렉서스", "лексус": "렉서스",
}

MODEL_MAP = {
    "tucson": "투싼", "туксон": "투싼",
    "santa fe": "싼타페", "санта фе": "싼타페",
    "palisade": "팰리세이드", "паллисад": "팰리세이드", "палисад": "팰리세이드",
    "ioniq": "아이오닉", "ионик": "아이오닉",
    "casper": "캐스퍼", "каспер": "캐스퍼",
    "avante": "아반떼", "аванте": "아반떼",
    "elantra": "아반떼", "элантра": "아반떼",
    "sonata": "쏘나타", "соната": "쏘나타",
    "sportage": "스포티지", "спортейдж": "스포티지",
    "sorento": "쏘렌토", "соренто": "쏘렌토",
    "carnival": "카니발", "карнивал": "카니발",
    "stinger": "스팅어", "стингер": "스팅어",
    "k5": "K5", "к5": "K5",
    "k8": "K8", "к8": "K8",
    "ev6": "EV6", "ев6": "EV6",
    "gv70": "GV70", "gv80": "GV80",
    "g80": "G80", "g90": "G90",
    "x5": "X5", "x6": "X6", "x7": "X7",
    "530": "530", "520": "520",
    "gle": "GLE", "glc": "GLC", "gls": "GLS",
    "g class": "G클래스", "g-class": "G클래스", "г класс": "G클래스",
}

COLOR_MAP = {
    "белый": "흰색", "белая": "흰색", "white": "흰색",
    "чёрный": "검정색", "черный": "검정색", "черная": "검정색", "black": "검정색",
    "серый": "회색", "серая": "회색", "gray": "회색", "grey": "회색",
    "серебро": "은색", "серебристый": "은색", "silver": "은색",
    "синий": "파란색", "синяя": "파란색", "blue": "파란색",
    "красный": "빨간색", "красная": "빨간색", "red": "빨간색",
    "коричневый": "갈색", "brown": "갈색",
    "зелёный": "녹색", "зеленый": "녹색", "green": "녹색",
    "бежевый": "베이지", "beige": "베이지",
    "оранжевый": "주황색", "orange": "주황색",
    "жёлтый": "노란색", "желтый": "노란색", "yellow": "노란색",
}


@dataclass
class EncarCar:
    car_id: int
    maker: str
    model: str
    badge: str
    year: int
    month: int
    mileage: int
    price_krw: int
    displacement_cc: int
    fuel_type: str
    photo_url: str
    encar_url: str
    photos: List[str] = None
    color: str = ""

    def __post_init__(self):
        if self.photos is None:
            self.photos = [self.photo_url] if self.photo_url else []

    @property
    def age_years(self) -> float:
        now = datetime.now()
        produced = datetime(self.year, max(self.month, 1), 1)
        return (now - produced).days / 365.25

    @property
    def fuel_ru(self) -> str:
        mapping = {
            "가솔린": "Бензин",
            "디젤": "Дизель",
            "전기": "Электро",
            "하이브리드": "Гибрид",
            "LPG": "Газ (LPG)",
        }
        return mapping.get(self.fuel_type, self.fuel_type)

    @property
    def is_electric(self) -> bool:
        return self.fuel_type in ("전기",)

    def short_title(self) -> str:
        return f"{self.maker} {self.model} {self.badge} {self.year}/{self.month:02d}"

    def encar_link(self) -> str:
        return f"https://www.encar.com/dc/dc_cardetailview.do?carid={self.car_id}"


def _build_query(
    price_max_man: int,
    price_min_man: int = 100,
    maker_ko: Optional[str] = None,
    model_ko: Optional[str] = None,
    max_displacement: Optional[int] = None,
    year_from: Optional[int] = None,
    max_mileage: Optional[int] = None,
    color_ko: Optional[str] = None,
) -> str:
    filters = [
        "Hidden.N",
        f"Price.[{price_min_man};{price_max_man}]",
    ]
    if maker_ko:
        filters.append(f"Maker.{maker_ko}")
    if model_ko:
        filters.append(f"Model.{model_ko}")
    if year_from:
        filters.append(f"Year.[{year_from}01;]")
    if max_mileage:
        filters.append(f"Mileage.[0;{max_mileage}]")
    if max_displacement:
        filters.append(f"Displacement.[0;{max_displacement}]")
    if color_ko:
        filters.append(f"Color.{color_ko}")
    inner = "._.".join(filters)
    return f"(And.{inner}.)"


async def search_cars(
    price_max_krw: int,
    price_min_krw: int = 1_000_000,
    maker: Optional[str] = None,
    makers: Optional[List[str]] = None,
    model: Optional[str] = None,
    year_from: Optional[int] = None,
    max_mileage: Optional[int] = None,
    max_displacement: Optional[int] = None,
    color: Optional[str] = None,
    limit: int = 8,
) -> List[EncarCar]:
    all_makers = makers if makers else ([maker] if maker else [None])
    if len(all_makers) > 1:
        tasks = [
            search_cars(
                price_max_krw=price_max_krw, price_min_krw=price_min_krw,
                maker=m, model=model, year_from=year_from,
                max_mileage=max_mileage, max_displacement=max_displacement,
                color=color, limit=limit,
            )
            for m in all_makers
        ]
        results_per_maker = await asyncio.gather(*tasks, return_exceptions=True)
        combined: List[EncarCar] = []
        for r in results_per_maker:
            if isinstance(r, list):
                combined.extend(r)
        seen = set()
        unique = []
        for car in sorted(combined, key=lambda c: c.price_krw):
            if car.car_id not in seen:
                seen.add(car.car_id)
                unique.append(car)
        return unique[:limit]

    single_maker = all_makers[0]
    price_max_man = price_max_krw // 10_000
    price_min_man = price_min_krw // 10_000

    maker_ko = MAKER_MAP.get(single_maker.lower().strip()) if single_maker else None
    model_ko = MODEL_MAP.get(model.lower().strip()) if model else None
    color_ko = COLOR_MAP.get(color.lower().strip()) if color else None

    q = _build_query(
        price_max_man=price_max_man, price_min_man=price_min_man,
        maker_ko=maker_ko, model_ko=model_ko,
        max_displacement=max_displacement, year_from=year_from,
        max_mileage=max_mileage, color_ko=color_ko,
    )

    url = "https://api.encar.com/search/car/list/general"
    params = {"count": "true", "q": q, "sr": f"|Price|0|{limit}"}
    headers = {
        "Referer": "https://www.encar.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("SearchResults", []):
        try:
            year_month = str(item.get("Year", "202201"))
            year = int(year_month[:4])
            month = int(year_month[4:6]) if len(year_month) >= 6 else 1

            photos_list: List[str] = []
            raw_photos = item.get("Photos") or []
            if isinstance(raw_photos, dict):
                raw_photos = [raw_photos]
            for p in raw_photos:
                if isinstance(p, dict):
                    path = p.get("location", "")
                    if path:
                        photos_list.append(f"https://ci.encar.com{path}")
                elif isinstance(p, str) and p:
                    photos_list.append(f"https://ci.encar.com{p}")
                if len(photos_list) >= 3:
                    break

            photo_url = photos_list[0] if photos_list else ""

            car = EncarCar(
                car_id=item.get("Id", 0),
                maker=item.get("Maker", ""),
                model=item.get("Model", ""),
                badge=item.get("Badge", ""),
                year=year,
                month=month,
                mileage=item.get("Mileage", 0),
                price_krw=item.get("Price", 0) * 10_000,
                displacement_cc=item.get("Displacement", 1600),
                fuel_type=item.get("FuelType", "가솔린"),
                photo_url=photo_url,
                encar_url=f"https://www.encar.com/dc/dc_cardetailview.do?carid={item.get('Id', 0)}",
                photos=photos_list,
                color=item.get("Color", ""),
            )
            results.append(car)
        except Exception:
            continue

    return results


def translate_maker(maker_ko: str) -> str:
    reverse = {v: k.title() for k, v in MAKER_MAP.items()}
    return reverse.get(maker_ko, maker_ko)
