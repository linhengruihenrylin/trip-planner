"""把資料來源、分析、規劃串在一起：app.py 和 CLI 都呼叫 run()。

source="real"：OSM + Google 地圖爬蟲（快取）+ Open-Meteo + OSRM
source="mock"：範例資料（離線備援，展示永遠不會壞）
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from analysis.correlation import correlation_matrix, crowd_correlations, place_level_corr
from analysis.crowd_model import CrowdModel, hourly_crowd
from analysis.history import build_history
from analysis.scoring import derive_weights, score_matrix
from data_sources.places import get_places
from data_sources.popular_times import get_popular_times
from data_sources.travel import travel_matrix
from data_sources.weather import get_weather, history_lookup, weather_for
from planner.itinerary import Planner, Plan


@dataclass
class Result:
    places: pd.DataFrame
    is_mock: bool
    weather: dict
    history: pd.DataFrame
    corr_matrix: pd.DataFrame
    crowd_corr: pd.DataFrame
    place_corr: dict
    model: CrowdModel
    weights: dict
    crowd: np.ndarray
    crowd_src: list[str]
    score: np.ndarray
    plans: list[Plan]
    info: dict = field(default_factory=dict)       # 資料來源說明、統計
    closed_today: pd.DataFrame = field(default_factory=pd.DataFrame)


def _load(source, region, date, mode, allow_network, refresh_weather):
    """回傳 (places, profiles, labels, weather, weather_fn, travel, info, closed)。"""
    if source == "mock":
        places, _ = get_places(region)
        profiles = {p.place_id: get_popular_times(p._asdict()) for p in places.itertuples(index=False)}
        labels = {k: "熱門時段（範例）" for k, v in profiles.items() if v is not None}
        info = {"source": "範例資料", "region_label": region, "travel_src": "直線距離估算"}
        return (places, profiles, labels, get_weather(date), None,
                travel_matrix(places.lat, places.lng, mode), info, pd.DataFrame())

    from data_sources import region_data as rd
    data = rd.load_region(region, allow_network=allow_network, log=lambda *_: None)
    if allow_network and refresh_weather:
        w = data.get("weather")
        if not w or w["fetched_at"][:10] != dt.date.today().isoformat():
            if rd.refresh_weather(data, log=lambda *_: None):
                rd.save(data)
    places, profiles, labels, closed = rd.to_frame(data, date)
    if places.empty:
        raise ValueError("這一天沒有任何候選地點營業")
    travel, travel_src = rd.travel_for(data, places, mode)
    st = rd.stats(data)
    info = {"source": "真實資料", "region_label": data["region_label"], "display_name": data["region"]["display_name"],
            "osm_fetched_at": data["osm_fetched_at"], "google_scraped_at": data.get("google_scraped_at"),
            "google_blocked": data.get("google_blocked"), "weather_fetched_at": (data.get("weather") or {}).get("fetched_at"),
            "travel_src": travel_src, "stats": st, "n_closed": len(closed)}
    return (places, profiles, labels, weather_for(data.get("weather"), date), history_lookup(data.get("weather")),
            travel, info, closed)


def run(region: str, date: dt.date, start_h: float, end_h: float,
        categories: list[str] | None = None, mode: str = "步行",
        crowd_aversion: float = config.DEFAULT_CROWD_AVERSION, n_plans: int = 5,
        seed: int = config.RANDOM_SEED, source: str = "mock", allow_network: bool = True,
        refresh_weather: bool = True) -> Result:
    categories = categories or config.CATEGORIES
    places, profiles, labels, weather, weather_fn, travel, info, closed = _load(
        source, region, date, mode, allow_network, refresh_weather)

    if sum(v is not None for v in profiles.values()) < 3:
        # 幾乎沒有人潮基準（例如還沒爬 Google）→ 全部用類別典型曲線，迴歸才有資料可學
        from data_sources.popular_times import estimated_profile
        for _, p in places.iterrows():
            if profiles.get(p.place_id) is None:
                profiles[p.place_id] = estimated_profile(p.to_dict())
                labels[p.place_id] = "類別典型曲線（無 Google 資料）"
    history = build_history(places, profiles, end=date, weather_fn=weather_fn)
    model = CrowdModel().fit(history)
    pc = place_level_corr(history)
    weights = derive_weights(pc, crowd_aversion)

    crowd, src = hourly_crowd(places, profiles, model, date.weekday(), weather,
                              hist_rain_mean=float(history.rain_prob.mean()), labels=labels)
    score = score_matrix(places, crowd, weights)
    planner = Planner(places, crowd, src, score, travel, start_h, end_h, categories, seed=seed)
    plans = planner.plans(n_plans=n_plans)

    return Result(places, source == "mock", weather, history, correlation_matrix(history),
                  crowd_correlations(history), pc, model, weights, crowd, src, score, plans, info, closed)
