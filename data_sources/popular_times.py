"""人潮曲線（每週 7 天 × 24 小時，0–100）。

- 真實資料：Google 地圖「熱門時段」由 data_sources/gmaps_scraper.py 爬取（未登入時通常拿不到）。
- 推估曲線 estimated_profile：Google 沒給熱門時段、但有「真實評論數」時，用
  「類別典型曲線（午餐/晚餐雙峰、下午景點高峰…）× 知名度（log 評論數）× 平假日倍率」推估，
  並套用 OSM 營業時間。這是**假設性的推估**，報告中需說明。
- 範例資料 mock_profile：同樣的曲線再加上隨機雜訊，並刻意讓約 15% 店家缺資料，示範迴歸補值。
"""
from __future__ import annotations

import zlib

import numpy as np

HOURS = np.arange(24)


def _bump(center: float, width: float, height: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((HOURS - center) / width) ** 2)


# 各類別的基本日間曲線（平日）
_BASE_SHAPE = {
    "景點": _bump(15.0, 2.6, 1.0) + _bump(10.5, 1.5, 0.35),
    "美食": _bump(12.2, 1.0, 1.0) + _bump(18.3, 1.2, 0.85) + _bump(8.0, 1.0, 0.3),
    "咖啡廳": _bump(15.5, 2.0, 1.0) + _bump(20.0, 1.5, 0.35),
}


def _curve(place: dict, rng, noise: float) -> np.ndarray:
    fame = np.clip(np.log10(max(place["reviews"], 1)) / np.log10(60000), 0.3, 1.0)
    shape = _BASE_SHAPE[place["category"]].copy()
    shape = np.roll(shape, rng.integers(-1, 2))  # 每家店尖峰略有不同
    week = np.zeros((7, 24))
    for d in range(7):
        weekend = 1.0 if d >= 5 else 0.0
        mult = 0.55 + 0.45 * weekend + rng.normal(0, 0.04)
        if d == 4:  # 週五晚上比較熱鬧
            mult += 0.1
        week[d] = shape * mult * fame * 100
    open_mask = (HOURS >= int(place["open_h"])) & (HOURS < int(np.ceil(place["close_h"])))
    week[:, ~open_mask] = 0
    return np.clip(week + rng.normal(0, noise, week.shape) * open_mask, 0, 100)


def mock_profile(place: dict) -> np.ndarray | None:
    """範例資料：回傳 shape=(7, 24) 的人潮曲線（0=週一 … 6=週日）。少部分店家回傳 None。"""
    rng = np.random.default_rng(zlib.crc32(place["place_id"].encode()))
    if place["place_id"].endswith(("3", "7")) and place["reviews"] < 10000:
        return None  # 模擬「Google 沒有這家店的熱門時段」
    return _curve(place, rng, noise=2.0)


def estimated_profile(place: dict) -> np.ndarray:
    """真實模式：用真實評論數與 OSM 營業時間推估的曲線（無隨機缺值、雜訊很小）。"""
    rng = np.random.default_rng(zlib.crc32(place["place_id"].encode()))
    return _curve(place, rng, noise=0.5)


def get_popular_times(place: dict) -> np.ndarray | None:
    """範例模式使用。"""
    return mock_profile(place)
