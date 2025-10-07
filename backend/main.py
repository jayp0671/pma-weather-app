from __future__ import annotations
import csv
import datetime as dt
import io
import json
import re
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from urllib.parse import quote_plus

# ===================== DB =====================
DB_URL = "sqlite:///app.db"  # creates app.db in the working dir (backend/)
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


class WeatherRequest(Base):
    __tablename__ = "weather_requests"
    id = Column(Integer, primary_key=True, index=True)
    input_location = Column(String, index=True)
    resolved_name = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    start_date = Column(Date)
    end_date = Column(Date)
    fetched_at = Column(DateTime, default=dt.datetime.utcnow)
    data_json = Column(Text)  # raw Open-Meteo daily payload


Base.metadata.create_all(bind=engine)

# ===================== API app =====================
app = FastAPI(title="PMA Weather App API", version="0.5.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== Geocode + Forecast =====================
GEOCODE_URL_OM = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ZIPPO_URL = "https://api.zippopotam.us/us"  # US ZIPs

# Basic parsing
COORD_RE = re.compile(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$")
ZIP_RE = re.compile(r"^\s*\d{5}\s*$")

# For light ranking of "City, ST"
STATE_ABBR = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME",
    "MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA",
    "RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"
}

# Be polite to public APIs
USER_AGENT = "PMA-Weather/1.0 (contact: your-email@example.com)"  # set to your email/GitHub

async def geocode_candidates(query: str) -> list[dict]:
    """
    Return list of {name, latitude, longitude, kind, source}.
    Supports: GPS, US ZIP, landmarks/cities via Nominatim, Open-Meteo fallback.
    """
    q = query.strip()
    candidates: list[dict] = []

    # 1) GPS (lat,lon)
    m = COORD_RE.match(q)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return [{
            "name": f"{lat:.4f}, {lon:.4f}",
            "latitude": lat,
            "longitude": lon,
            "kind": "gps",
            "source": "user"
        }]

    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": USER_AGENT}) as client:
        # 2) US ZIP
        if ZIP_RE.match(q):
            try:
                zr = await client.get(f"{ZIPPO_URL}/{q}")
                if zr.status_code == 200:
                    z = zr.json()
                    for p in z.get("places", []):
                        name = f"{p['place name']}, {p['state abbreviation']}, USA {z['post code']}"
                        lat = float(p["latitude"])
                        lon = float(p["longitude"])
                        candidates.append({
                            "name": name,
                            "latitude": lat,
                            "longitude": lon,
                            "kind": "postal",
                            "source": "zippopotam"
                        })
            except Exception:
                pass

        # 3) Landmarks / City,ST — Nominatim (up to 5)
        try:
            nr = await client.get(
                NOMINATIM_URL,
                params={"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 1}
            )
            if nr.status_code == 200:
                arr = nr.json() or []
                for item in arr:
                    name = item.get("display_name") or q
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    kind = item.get("type") or "place"
                    candidates.append({
                        "name": name,
                        "latitude": lat,
                        "longitude": lon,
                        "kind": kind,
                        "source": "nominatim"
                    })
        except Exception:
            pass

        # 4) Open-Meteo geocoder fallback
        try:
            parts = [p.strip() for p in q.split(",") if p.strip()]
            params = {"name": q, "count": 3, "language": "en"}
            if len(parts) >= 2 and parts[1].upper() in STATE_ABBR:
                params["name"] = parts[0]
                params["countryCode"] = "US"

            om = await client.get(GEOCODE_URL_OM, params=params)
            if om.status_code == 200:
                data = om.json()
                for r in (data.get("results") or [])[:3]:
                    disp = ", ".join([x for x in [r.get("name"), r.get("admin1"), r.get("country")] if x])
                    candidates.append({
                        "name": disp,
                        "latitude": r["latitude"],
                        "longitude": r["longitude"],
                        "kind": "place",
                        "source": "open-meteo"
                    })
        except Exception:
            pass

    # De-dup by rounded lat/lon
    seen = set()
    uniq: list[dict] = []
    for c in candidates:
        key = (round(c["latitude"], 4), round(c["longitude"], 4))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


async def resolve_location(q: str) -> dict:
    cands = await geocode_candidates(q)
    if not cands:
        raise HTTPException(404, detail="Location not found")

    def rank(c: dict) -> int:
        order = {"postal": 0, "place": 1, "town": 1, "city": 1, "hamlet": 1, "village": 1, "gps": 2}
        return order.get(c.get("kind"), 5)

    cands.sort(key=rank)
    top = cands[0]
    return {"name": top["name"], "latitude": top["latitude"], "longitude": top["longitude"]}


async def fetch_current_and_5day(lat: float, lon: float) -> dict:
    today = dt.date.today()
    end = today + dt.timedelta(days=5)
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "weather_code",
            "wind_speed_10m",
        ],
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "weather_code",
            "wind_speed_10m_max",
        ],
        "timezone": "auto",
        "start_date": today.isoformat(),
        "end_date": end.isoformat(),
    }
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(FORECAST_URL, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_range(lat: float, lon: float, start_date: dt.date, end_date: dt.date) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "weather_code",
            "wind_speed_10m_max",
        ],
        "timezone": "auto",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(FORECAST_URL, params=params)
        r.raise_for_status()
        return r.json()

# ===================== Schemas =====================
class CreateRequest(BaseModel):
    location: str = Field(..., description="Zip/City/GPS/etc")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")


class UpdateRequest(BaseModel):
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

# ===================== Assessment 1 =====================
@app.get("/api/weather/current")
async def get_current(
    location: str = Query(..., description="Zip/City/GPS e.g. '07302' or '40.7,-74.0'")
):
    loc = await resolve_location(location)
    data = await fetch_current_and_5day(loc["latitude"], loc["longitude"])
    return {"resolved": loc, "data": data}

# Optional helper
@app.get("/api/locations/search")
async def location_search(q: str = Query(..., description="Zip/City/landmark/GPS")):
    return await geocode_candidates(q)

# ===================== Assessment 2: CRUD =====================
@app.post("/api/records")
async def create_record(req: CreateRequest):
    try:
        s = dt.date.fromisoformat(req.start_date)
        e = dt.date.fromisoformat(req.end_date)
    except Exception:
        raise HTTPException(400, detail="Invalid date format. Use YYYY-MM-DD.")
    if e < s:
        raise HTTPException(400, detail="end_date must be on/after start_date")

    loc = await resolve_location(req.location)
    data = await fetch_range(loc["latitude"], loc["longitude"], s, e)

    rec = WeatherRequest(
        input_location=req.location,
        resolved_name=loc["name"],
        latitude=loc["latitude"],
        longitude=loc["longitude"],
        start_date=s,
        end_date=e,
        data_json=json.dumps(data),
    )
    db = SessionLocal()
    try:
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return {"id": rec.id, "message": "created", "resolved": loc}
    finally:
        db.close()


@app.get("/api/records")
async def list_records():
    db = SessionLocal()
    try:
        rows = db.query(WeatherRequest).order_by(WeatherRequest.id.desc()).all()
        return [
            {
                "id": r.id,
                "input_location": r.input_location,
                "resolved_name": r.resolved_name,
                "lat": r.latitude,
                "lon": r.longitude,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.get("/api/records/{rec_id}")
async def get_record(rec_id: int):
    db = SessionLocal()
    try:
        r = db.query(WeatherRequest).get(rec_id)
        if not r:
            raise HTTPException(404, detail="record not found")
        return {
            "id": r.id,
            "input_location": r.input_location,
            "resolved_name": r.resolved_name,
            "lat": r.latitude,
            "lon": r.longitude,
            "start_date": r.start_date.isoformat() if r.start_date else None,
            "end_date": r.end_date.isoformat() if r.end_date else None,
            "data": json.loads(r.data_json) if r.data_json else None,
        }
    finally:
        db.close()


@app.put("/api/records/{rec_id}")
async def update_record(rec_id: int, body: UpdateRequest):
    db = SessionLocal()
    try:
        r = db.query(WeatherRequest).get(rec_id)
        if not r:
            raise HTTPException(404, detail="record not found")

        if body.location:
            loc = await resolve_location(body.location)
            r.input_location = body.location
            r.resolved_name = loc["name"]
            r.latitude = loc["latitude"]
            r.longitude = loc["longitude"]
        if body.start_date:
            r.start_date = dt.date.fromisoformat(body.start_date)
        if body.end_date:
            r.end_date = dt.date.fromisoformat(body.end_date)
        if r.end_date < r.start_date:
            raise HTTPException(400, detail="end_date must be on/after start_date")

        new_data = await fetch_range(r.latitude, r.longitude, r.start_date, r.end_date)
        r.data_json = json.dumps(new_data)
        r.fetched_at = dt.datetime.utcnow()

        db.commit()
        db.refresh(r)
        return {"id": r.id, "message": "updated"}
    finally:
        db.close()


@app.delete("/api/records/{rec_id}")
async def delete_record(rec_id: int):
    db = SessionLocal()
    try:
        r = db.query(WeatherRequest).get(rec_id)
        if not r:
            raise HTTPException(404, detail="record not found")
        db.delete(r)
        db.commit()
        return {"id": rec_id, "message": "deleted"}
    finally:
        db.close()

# ===================== Export (optional) =====================
@app.get("/api/export")
async def export_records(fmt: str = Query("json", enum=["json", "csv", "xml", "md"])):
    db = SessionLocal()
    try:
        rows = db.query(WeatherRequest).order_by(WeatherRequest.id.asc()).all()
        rows_s = [
            {
                "id": r.id,
                "input_location": r.input_location,
                "resolved_name": r.resolved_name,
                "lat": r.latitude,
                "lon": r.longitude,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]

        if fmt == "json":
            return rows_s

        if fmt == "csv":
            buf = io.StringIO()
            if rows_s:
                writer = csv.DictWriter(buf, fieldnames=list(rows_s[0].keys()))
                writer.writeheader()
                writer.writerows(rows_s)
            return Response(content=buf.getvalue(), media_type="text/csv")

        if fmt == "xml":
            from xml.sax.saxutils import escape
            parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<records>"]
            for r in rows_s:
                parts.append("  <record>")
                for k, v in r.items():
                    val = "" if v is None else str(v)
                    parts.append(f"    <{k}>{escape(val)}</{k}>")
                parts.append("  </record>")
            parts.append("</records>")
            xml_text = "\n".join(parts)
            return Response(content=xml_text, media_type="application/xml")

        if fmt == "md":
            if not rows_s:
                md = "(no records)"
            else:
                headers = list(rows_s[0].keys())
                lines = [
                    "| " + " | ".join(headers) + " |",
                    "| " + " | ".join(["---"] * len(headers)) + " |",
                ]
                for r in rows_s:
                    lines.append("| " + " | ".join([str(r[h]) for h in headers]) + " |")
                md = "\n".join(lines)
            return Response(content=md, media_type="text/markdown")

    finally:
        db.close()

# ===================== API Integration 2.2 (no YouTube, no maps) =====================

# Nearby POIs via Overpass API (free)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

@app.get("/api/places/nearby")
async def nearby_places(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: int = Query(1000, ge=100, le=5000),
    limit: int = Query(20, ge=1, le=50)
):
    filters = [
        'tourism~"attraction|museum|artwork|viewpoint"',
        'amenity~"cafe|restaurant|fast_food|bar|pub"',
        'leisure~"park|garden"'
    ]
    q = f"""
    [out:json][timeout:25];
    (
      node[{filters[0]}](around:{radius},{lat},{lon});
      node[{filters[1]}](around:{radius},{lat},{lon});
      node[{filters[2]}](around:{radius},{lat},{lon});
      way[{filters[0]}](around:{radius},{lat},{lon});
      way[{filters[1]}](around:{radius},{lat},{lon});
      way[{filters[2]}](around:{radius},{lat},{lon});
    );
    out center {limit};
    """
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.post(OVERPASS_URL, data={"data": q})
        if r.status_code != 200:
            raise HTTPException(502, detail="Overpass API error")
        data = r.json()

    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if el["type"] == "node":
            la, lo = el.get("lat"), el.get("lon")
        else:  # way
            center = el.get("center") or {}
            la, lo = center.get("lat"), center.get("lon")
        if la is None or lo is None:
            continue

        cat = (
            tags.get("tourism")
            or tags.get("amenity")
            or tags.get("leisure")
            or "place"
        )
        out.append({
            "id": el.get("id"),
            "name": name,
            "category": cat,
            "lat": la,
            "lon": lo
        })
        if len(out) >= limit:
            break

    return {"lat": lat, "lon": lon, "radius": radius, "items": out}

# Sunrise/Sunset (keyless)
@app.get("/api/extras/astronomy")
async def astronomy(
    lat: float = Query(...),
    lon: float = Query(...)
):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0"
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(502, detail="Astronomy API error")
        j = r.json()
    if j.get("status") != "OK":
        raise HTTPException(502, detail="Astronomy API unavailable")
    return j.get("results", {})

# Air Quality (Open-Meteo)
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

def _round(v, nd=1):
    try:
        return None if v is None else round(float(v), nd)
    except Exception:
        return None

@app.get("/api/extras/air")
async def air_quality(lat: float = Query(...), lon: float = Query(...)):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone,sulphur_dioxide",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(AIR_URL, params=params)
        if r.status_code != 200:
            raise HTTPException(502, detail="Air quality service unavailable")
        j = r.json()

    hourly = j.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return {"now": None}

    idx = len(times) - 1
    def gv(name):
        arr = hourly.get(name) or []
        return arr[idx] if idx < len(arr) else None

    now = {
        "time": times[idx],
        "us_aqi": gv("us_aqi"),
        "pm2_5": _round(gv("pm2_5"), 1),
        "pm10": _round(gv("pm10"), 1),
        "ozone": _round(gv("ozone"), 1),
        "nitrogen_dioxide": _round(gv("nitrogen_dioxide"), 1),
        "sulphur_dioxide": _round(gv("sulphur_dioxide"), 1),
        "carbon_monoxide": _round(gv("carbon_monoxide"), 1),
    }
    return {"now": now}

# Pollen Forecast (Open-Meteo; some regions have none)
POLLEN_URL = "https://pollen-api.open-meteo.com/v1/forecast"

@app.get("/api/extras/pollen")
async def pollen(lat: float = Query(...), lon: float = Query(...)):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "alder_pollen,birch_pollen,grass_pollen,olive_pollen,ragweed_pollen",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(POLLEN_URL, params=params)
        if r.status_code != 200:
            return {"daily": []}
        j = r.json()

    daily = j.get("daily") or {}
    days = daily.get("time") or []
    out = []
    for i, d in enumerate(days[:5]):  # 5 days
        out.append({
            "date": d,
            "grass": daily.get("grass_pollen", [None]*len(days))[i],
            "birch": daily.get("birch_pollen", [None]*len(days))[i],
            "olive": daily.get("olive_pollen", [None]*len(days))[i],
            "alder": daily.get("alder_pollen", [None]*len(days))[i],
            "ragweed": daily.get("ragweed_pollen", [None]*len(days))[i],
        })
    return {"daily": out}

# Wikipedia: nearest page summary + thumbnail (keyless)
WIKI_GEOSEARCH = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

@app.get("/api/extras/wiki")
async def wiki_nearby(lat: float = Query(...), lon: float = Query(...)):
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(WIKI_GEOSEARCH, params={
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": 10000,
            "gslimit": 1,
            "format": "json"
        })
        if r.status_code != 200:
            return {"title": None, "extract": None, "url": None, "thumbnail": None}
        q = r.json()
        results = (q.get("query") or {}).get("geosearch") or []
        if not results:
            return {"title": None, "extract": None, "url": None, "thumbnail": None}
        title = results[0]["title"]

        sr = await client.get(WIKI_SUMMARY.format(title=quote_plus(title)))
        if sr.status_code != 200:
            return {"title": title, "extract": None, "url": None, "thumbnail": None}
        s = sr.json()
        return {
            "title": s.get("title"),
            "extract": s.get("extract"),
            "url": s.get("content_urls", {}).get("desktop", {}).get("page"),
            "thumbnail": (s.get("thumbnail") or {}).get("source"),
        }

# “Today in history” (Numbers API)
NUMBERS_DATE = "http://numbersapi.com/{mm}/{dd}/date?json"

@app.get("/api/extras/datefact")
async def date_fact():
    today = dt.date.today()
    mm, dd = today.month, today.day
    url = NUMBERS_DATE.format(mm=mm, dd=dd)
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return {"text": None, "year": None}
        j = r.json()
        return {"text": j.get("text"), "year": j.get("year")}

@app.get("/api/health")
async def health():
    return {"status": "ok"}
