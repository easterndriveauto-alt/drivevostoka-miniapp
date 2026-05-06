"""
api.py — FastAPI сервер для DriveVostoka Mini App
"""

import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from calculator import CarSpec, calculate, estimate_max_car_price_krw
from currency import get_rates
from database import init_db, migrate_db, save_lead as db_save_lead, upsert_client
from encar import search_cars
from tools import KRW_MARKUP, _hp_by_cc

app = FastAPI(title="DriveVostoka Mini App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
async def startup():
    init_db()
    migrate_db()


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/rates")
async def api_rates():
    krw_raw, eur, usd = await get_rates()
    krw = krw_raw + KRW_MARKUP
    return {
        "KRW_RUB": round(krw, 4),
        "KRW_RUB_CBR": round(krw_raw, 4),
        "EUR_RUB": round(eur, 2),
        "USD_RUB": round(usd, 2),
    }


@app.get("/api/search")
async def api_search(
    budget_rub: float = 2_500_000,
    maker: Optional[str] = None,
    model: Optional[str] = None,
    year_from: Optional[int] = None,
    max_mileage: Optional[int] = None,
    displacement_max: Optional[int] = None,
    is_electric: bool = False,
):
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
        model=model,
        year_from=year_from,
        max_mileage=max_mileage,
        max_displacement=displacement_max,
        limit=8,
    )

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

        results.append({
            "id": car.car_id,
            "title": f"{car.maker} {car.model} {car.badge}".strip(),
            "maker": car.maker,
            "model": car.model,
            "year": car.year,
            "month": car.month,
            "mileage": car.mileage,
            "displacement_cc": car.displacement_cc,
            "fuel": car.fuel_ru,
            "color": car.color,
            "price_korea_rub": round(car.price_krw * krw_rub),
            "total_vladivostok_rub": round(cost.total),
            "encar_url": f"https://www.encar.com/dc/dc_cardetailview.do?carid={car.car_id}",
            "photos": car.photos[:2],
            "breakdown": {
                "car_with_delivery": round(cost.car_price_rub + cost.shipping_vvo + cost.customs_broker),
                "duty":              round(cost.customs_duty + cost.excise + cost.vat),
                "customs_fee":       round(cost.customs_clearance),
                "util_sbor":         round(cost.util_sbor),
            },
        })

    return {
        "found": len(results),
        "budget_rub": budget_rub,
        "krw_rate": round(krw_rub, 4),
        "results": results,
    }


class LeadRequest(BaseModel):
    name: str
    phone: str
    car_title: str
    budget_rub: float = 0
    city: str = ""
    chat_id: int = 0


@app.post("/api/lead")
async def api_lead(req: LeadRequest):
    if req.chat_id:
        upsert_client(req.chat_id)
    lead_id = db_save_lead(
        chat_id=req.chat_id,
        name=req.name,
        phone=req.phone,
        car_choice=req.car_title,
        budget_rub=req.budget_rub,
        city=req.city,
    )
    return {"status": "ok", "lead_id": lead_id}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
