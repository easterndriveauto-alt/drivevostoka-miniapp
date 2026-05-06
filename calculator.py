"""
calculator.py — Расчёт стоимости ввоза автомобиля из Кореи в РФ
Ставки таможенных пошлин: ЕАЭС (физические лица)
Утилизационный сбор: актуальные коэффициенты с 01.12.2025
"""

from dataclasses import dataclass, field
from typing import Optional


UTIL_BASE = 20_000

UTIL_RATES = [
    (1000,  0.75,  0.75,  1.57),
    (2000,  4.49,  5.17,  9.37),
    (3000,  9.08, 12.98, 21.90),
    (3500, 12.98, 16.26, 26.44),
    (4500, 13.56, 17.18, 27.97),
    (5500, 15.25, 19.15, 31.04),
    (9999, 17.54, 22.51, 35.72),
]

DUTY_UNDER3 = [
    (1000, 0.54, 2.5),
    (1500, 0.54, 3.5),
    (1800, 0.54, 5.0),
    (2300, 0.54, 7.5),
    (3000, 0.54, 7.5),
    (9999, 0.54, 15.0),
]
DUTY_3_5 = [
    (1000, 0.20, 1.2),
    (1500, 0.20, 1.5),
    (1800, 0.20, 2.5),
    (2300, 0.20, 2.5),
    (3000, 0.20, 2.5),
    (9999, 0.20, 5.7),
]
DUTY_OVER5 = [
    (1000, 0.20, 1.4),
    (1500, 0.20, 1.7),
    (1800, 0.20, 2.5),
    (2300, 0.20, 2.7),
    (3000, 0.20, 2.7),
    (9999, 0.20, 6.6),
]

EXCISE_RATES = [
    (90,  0),
    (150, 61),
    (200, 583),
    (300, 809),
    (400, 1267),
    (500, 1310),
    (9999, 1354),
]

SHIPPING_KOREA_VVO = 120_000

CITY_DELIVERY = {
    "владивосток":   0,
    "хабаровск":    25_000,
    "новосибирск":  65_000,
    "красноярск":   70_000,
    "иркутск":      55_000,
    "омск":         70_000,
    "екатеринбург": 85_000,
    "челябинск":    87_000,
    "тюмень":       82_000,
    "уфа":          90_000,
    "казань":       95_000,
    "нижний новгород": 100_000,
    "самара":       97_000,
    "москва":      110_000,
    "санкт-петербург": 115_000,
    "краснодар":   108_000,
    "ростов-на-дону": 105_000,
    "воронеж":     103_000,
    "default":      90_000,
}

CUSTOMS_BROKER_FEE = 55_000
CUSTOMS_CLEARANCE_FEE = 7_500


@dataclass
class CarSpec:
    price_krw: int
    displacement_cc: int
    power_hp: int
    age_years: float
    is_electric: bool = False
    city: str = "default"


@dataclass
class ImportCost:
    car_price_rub: float
    customs_duty: float
    excise: float
    vat: float
    util_sbor: float
    customs_clearance: float
    customs_broker: float
    shipping_vvo: float
    shipping_city: float

    @property
    def total(self) -> float:
        return (
            self.car_price_rub + self.customs_duty + self.excise +
            self.vat + self.util_sbor + self.customs_clearance +
            self.customs_broker + self.shipping_vvo + self.shipping_city
        )

    def as_dict(self) -> dict:
        return {
            "🚗 Стоимость авто (в России)":      round(self.car_price_rub),
            "🛃 Таможенная пошлина":              round(self.customs_duty),
            "⚡ Акциз":                           round(self.excise),
            "💰 НДС 20%":                         round(self.vat),
            "♻️ Утилизационный сбор (с 01.12.25)": round(self.util_sbor),
            "📋 Таможенный сбор":                  round(self.customs_clearance),
            "🤝 Брокер + оформление":              round(self.customs_broker),
            "🚢 Доставка Корея → Владивосток":    round(self.shipping_vvo),
            "🚛 Доставка до вашего города":        round(self.shipping_city),
            "✅ ИТОГО под ключ":                   round(self.total),
        }

    def summary_text(self) -> str:
        lines = []
        for k, v in self.as_dict().items():
            if k.startswith("✅"):
                lines.append(f"\n<b>{k}: {v:,} ₽</b>")
            else:
                lines.append(f"  {k}: {v:,} ₽")
        return "\n".join(lines)


def _get_util_coefficient(displacement_cc: int, age_years: float) -> float:
    def as_dict(self) -> dict:
        car_with_delivery = round(self.car_price_rub + self.shipping_vvo + self.customs_broker)
        total_duty = round(self.customs_duty + self.excise + self.vat)
        return {
            "🚗 Цена авто в Корее (с доставкой и оформлением)": car_with_delivery,
            "🛃 Пошлина":                                        total_duty,
            "📋 Таможенный сбор":                                round(self.customs_clearance),
            "♻️ Утилизационный сбор":                           round(self.util_sbor),
            "✅ Итого под ключ в порту г.Владивосток":                                 round(self.total),
        }
    if age_years < 3:
        table = DUTY_UNDER3
    elif age_years <= 5:
        table = DUTY_3_5
    else:
        table = DUTY_OVER5

    for max_cc, pct, eur_cc in table:
        if displacement_cc <= max_cc:
            return pct, eur_cc
    return table[-1][1], table[-1][2]


def _get_excise(power_hp: int) -> float:
    for max_hp, rate in EXCISE_RATES:
        if power_hp <= max_hp:
            return power_hp * rate
    return power_hp * EXCISE_RATES[-1][1]


def calculate(spec: CarSpec, rate_krw_rub: float, rate_eur_rub: float) -> ImportCost:
    car_rub = spec.price_krw * rate_krw_rub

    if spec.is_electric:
        duty = car_rub * 0.15
        excise = 0.0
        util = UTIL_BASE * 1.63
        vat = (car_rub + duty) * 0.20
    else:
        car_eur = car_rub / rate_eur_rub
        pct_rate, eur_cc_rate = _get_duty_rate(spec.displacement_cc, spec.age_years)
        duty_pct = car_eur * pct_rate
        duty_eur_cc = eur_cc_rate * spec.displacement_cc
        duty_eur = max(duty_pct, duty_eur_cc)
        duty = duty_eur * rate_eur_rub

        excise = _get_excise(spec.power_hp)
        vat = (car_rub + duty + excise) * 0.20

        coef = _get_util_coefficient(spec.displacement_cc, spec.age_years)
        util = UTIL_BASE * coef

    city_key = spec.city.lower().strip()
    delivery_city = CITY_DELIVERY.get(city_key, CITY_DELIVERY["default"])

    return ImportCost(
        car_price_rub=car_rub,
        customs_duty=duty,
        excise=excise,
        vat=vat,
        util_sbor=util,
        customs_clearance=CUSTOMS_CLEARANCE_FEE,
        customs_broker=CUSTOMS_BROKER_FEE,
        shipping_vvo=SHIPPING_KOREA_VVO,
        shipping_city=delivery_city,
    )


def estimate_max_car_price_krw(
    budget_rub: float,
    displacement_cc: int,
    age_years: float,
    power_hp: int,
    city: str,
    rate_krw_rub: float,
    rate_eur_rub: float,
    is_electric: bool = False,
) -> int:
    lo, hi = 1_000_000, 200_000_000

    for _ in range(40):
        mid = (lo + hi) // 2
        spec = CarSpec(
            price_krw=mid,
            displacement_cc=displacement_cc,
            power_hp=power_hp,
            age_years=age_years,
            is_electric=is_electric,
            city=city,
        )
        total = calculate(spec, rate_krw_rub, rate_eur_rub).total
        if total < budget_rub:
            lo = mid
        else:
            hi = mid

    return lo
