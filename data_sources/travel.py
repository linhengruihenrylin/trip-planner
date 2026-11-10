"""交通時間。

- 真實資料：OSRM 公開示範伺服器（router.project-osrm.org，免費、免金鑰）的 table 服務，
  取得「實際道路距離」與開車時間。示範伺服器只提供汽車路網，所以：
    步行 = OSRM 道路距離 ÷ 4.5 km/h
    機車 = OSRM 道路距離 ÷ 22 km/h + 3 分鐘（停車）
    開車 = OSRM 開車時間 + 8 分鐘（找車位）
  使用規範：示範伺服器僅供輕量使用，本專案每個地區每種交通方式只查一次並快取。
- 失敗或離線時：Haversine 直線距離 × 繞路係數 ÷ 平均速度。
"""
from __future__ import annotations

import numpy as np
import requests

import config


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lng2) - np.radians(lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def travel_matrix(lats, lngs, mode: str = "步行") -> np.ndarray:
    """Haversine 估算：回傳 N×N 的移動分鐘數矩陣。"""
    lats, lngs = np.asarray(lats), np.asarray(lngs)
    km = haversine_km(lats[:, None], lngs[:, None], lats[None, :], lngs[None, :])
    minutes = km * config.DETOUR_FACTOR / config.SPEED_KMH[mode] * 60
    minutes = minutes + config.TRANSFER_OVERHEAD_MIN[mode]
    np.fill_diagonal(minutes, 0)
    return np.ceil(minutes)


def fetch_osrm_table(lats, lngs) -> dict:
    """回傳 {"distance_m": N×N, "duration_s": N×N}（list of lists）。"""
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in zip(lats, lngs))
    r = requests.get(f"{config.OSRM_URL}/table/v1/driving/{coords}",
                     params={"annotations": "duration,distance"}, timeout=30,
                     headers={"User-Agent": config.HTTP_USER_AGENT})
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "Ok":
        raise RuntimeError(f"OSRM 回應：{j.get('code')}")
    return {"distance_m": j["distances"], "duration_s": j["durations"]}


def minutes_from_osrm(table: dict, mode: str) -> np.ndarray:
    dist = np.array(table["distance_m"], dtype=float)
    dur = np.array(table["duration_s"], dtype=float)
    if mode == "開車":
        m = dur / 60
    else:
        m = dist / 1000 / config.SPEED_KMH[mode] * 60
    m = m + config.TRANSFER_OVERHEAD_MIN[mode]
    np.fill_diagonal(m, 0)
    return np.ceil(np.nan_to_num(m, nan=999))
