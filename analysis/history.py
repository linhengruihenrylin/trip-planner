"""把「熱門時段曲線 × 過去天氣」展開成一張歷史觀測表，給相關係數與迴歸使用。

- 真實資料模式：天氣用 Open-Meteo 的「過去 8 週逐時實際資料」；人潮基準用 Google 熱門時段
  （拿不到時用「類別曲線 × 真實評論數」推估曲線），再套用天氣效果 → 每家店 × 每天 × 每小時一筆觀測。
- 範例資料模式：天氣也用範例天氣。
天氣對人潮的效果（weather_effect）是依常識設定的假設，報告中要說明。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from data_sources.weather import mock_weather


def weather_effect(crowd, rain, temp, indoor):
    """天氣對人潮的影響（模擬用）：下雨戶外變少、室內變多；太熱戶外變少。"""
    outdoor_mult = (1 - 0.45 * rain) * (1 - 0.02 * np.maximum(temp - 30, 0))
    indoor_mult = 1 + 0.20 * rain
    return crowd * np.where(indoor, indoor_mult, outdoor_mult)


def build_history(places: pd.DataFrame, profiles: dict, end: dt.date, weeks: int = 8,
                  seed: int = 0, weather_fn=None) -> pd.DataFrame:
    """weather_fn(day) -> {"rain_prob", "temp_c"}；預設用範例天氣。"""
    rng = np.random.default_rng(seed)
    weather_fn = weather_fn or mock_weather
    rows = []
    for k in range(weeks * 7):
        day = end - dt.timedelta(days=k + 1)
        w = weather_fn(day)
        wd = day.weekday()
        for _, p in places.iterrows():
            prof = profiles.get(p.place_id)
            if prof is None:
                continue
            for h in range(int(p.open_h), int(np.ceil(p.close_h))):
                if h < 7 or h > 22:
                    continue
                base = prof[wd, h]
                crowd = weather_effect(base, w["rain_prob"], w["temp_c"], p.indoor)
                crowd = float(np.clip(crowd + rng.normal(0, 4), 0, 100))
                rows.append({
                    "place_id": p.place_id, "name": p["name"], "category": p.category,
                    "date": day, "hour": h, "weekday": wd, "is_weekend": int(wd >= 5),
                    "rain_prob": w["rain_prob"], "temp_c": w["temp_c"],
                    "rating": p.rating, "log_reviews": np.log10(p.reviews),
                    "indoor": int(p.indoor), "crowd": crowd,
                })
    return pd.DataFrame(rows)
