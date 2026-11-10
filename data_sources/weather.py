"""天氣資料。

- 真實資料：Open-Meteo（免費、免金鑰）。一次抓「過去 61 天 + 未來 16 天」的逐時降雨機率與氣溫：
  未來的部分給行程當天用，過去的部分當作歷史觀測表的天氣（相關係數、迴歸用）。
- 範例資料：用日期當亂數種子產生「可重現」的天氣（降雨機率、氣溫）。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import requests

import config

DAY_HOURS = range(9, 19)  # 用 09–18 時的白天時段代表當天天氣


def mock_weather(date: dt.date) -> dict:
    rng = np.random.default_rng(date.toordinal())
    rain = float(np.clip(rng.beta(1.2, 3.5), 0, 1))
    month_temp = {1: 18, 2: 19, 3: 22, 4: 25, 5: 28, 6: 30, 7: 31, 8: 31, 9: 30, 10: 27, 11: 24, 12: 20}
    temp = month_temp[date.month] + rng.normal(0, 1.5)
    return {"rain_prob": round(rain, 2), "temp_c": round(float(temp), 1), "source": "範例資料"}


def get_weather(date: dt.date, district: str = "") -> dict:
    """範例模式用（保留舊介面）。"""
    return mock_weather(date)


def fetch_open_meteo(lat: float, lng: float) -> dict:
    r = requests.get(config.OPEN_METEO_URL, timeout=20, params={
        "latitude": round(lat, 4), "longitude": round(lng, 4),
        "hourly": "precipitation_probability,temperature_2m",
        "timezone": "Asia/Taipei", "past_days": 61, "forecast_days": 16,
    }, headers={"User-Agent": config.HTTP_USER_AGENT})
    r.raise_for_status()
    h = r.json()["hourly"]
    return {"lat": lat, "lng": lng, "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "time": h["time"], "precipitation_probability": h["precipitation_probability"],
            "temperature_2m": h["temperature_2m"]}


def day_summary(hourly: dict, date: dt.date) -> dict | None:
    """把逐時資料整理成一天：白天最高降雨機率、白天平均氣溫、逐時明細。"""
    key = date.isoformat()
    rows = [(int(t[11:13]), p, tc) for t, p, tc in
            zip(hourly["time"], hourly["precipitation_probability"], hourly["temperature_2m"])
            if t.startswith(key)]
    if not rows:
        return None
    day = [(h, p, tc) for h, p, tc in rows if h in DAY_HOURS and tc is not None]
    if not day:
        return None
    probs = [p for _, p, _ in day if p is not None]
    return {"rain_prob": round(max(probs) / 100, 2) if probs else 0.2,
            "temp_c": round(float(np.mean([tc for _, _, tc in day])), 1),
            "hourly_rain": {h: p for h, p, _ in rows}, "hourly_temp": {h: tc for h, _, tc in rows}}


def weather_for(hourly: dict | None, date: dt.date) -> dict:
    """行程當天的天氣；超出 Open-Meteo 範圍時退回範例天氣並標示。"""
    if hourly:
        s = day_summary(hourly, date)
        if s:
            past = date < dt.date.fromisoformat(hourly["fetched_at"][:10])
            return dict(s, source=f"Open-Meteo（{'過去實況' if past else '預報'}，抓取於 {hourly['fetched_at'][:16].replace('T', ' ')}）")
    w = mock_weather(date)
    w["source"] = "範例天氣（日期超出 Open-Meteo 預報範圍或無法連線）"
    return w


def history_lookup(hourly: dict | None):
    """給 analysis.history 用：回傳 day -> {rain_prob, temp_c, real}。"""
    def f(day: dt.date) -> dict:
        if hourly:
            s = day_summary(hourly, day)
            if s:
                return {"rain_prob": s["rain_prob"], "temp_c": s["temp_c"], "real": True}
        w = mock_weather(day)
        return {"rain_prob": w["rain_prob"], "temp_c": w["temp_c"], "real": False}
    return f
