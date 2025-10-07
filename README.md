# PMA Weather — Jay Patel

A full-stack weather app for PM Accelerator’s AI Engineer Intern assessment.

## Features

- **Tech Assessment 1**
  - Flexible location input: ZIP, GPS (`lat,lon`), landmarks, towns/cities
  - Current weather (Open-Meteo) + **5-day forecast**
  - **Use My Location** (browser geolocation)
  - Clear, icon/emoji-based UI

- **Tech Assessment 2**
  - **CRUD with persistence (SQLite)**: save location + date range and fetch daily temps
  - Input validation (dates; location resolution with multiple geocoders)
  - Optional integrations:
    - **Nearby places** via OpenStreetMap Overpass
    - **Astronomy** (sunrise/sunset)
    - **Air Quality** (US AQI snapshot)
  - **Export** saved records: **JSON, CSV, XML, Markdown**

UI includes my name and a link to the PMA LinkedIn page.

## Stack

- Frontend: React + Vite
- Backend: FastAPI (Python), SQLAlchemy, SQLite
- APIs: Open-Meteo (weather + geocode), OpenStreetMap Overpass (POIs), Sunrise-Sunset (astronomy)

## Quickstart

### 1) Backend
```bash
cd backend
# (optional) python -m venv .venv && . .venv/Scripts/activate  # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
