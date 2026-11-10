"""真實資料模組的離線測試（不連網、不開瀏覽器）：python tests/test_real_data.py 或 pytest"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from data_sources import gmaps_scraper as gs  # noqa: E402
from data_sources import osm  # noqa: E402
from data_sources import region_data as rd  # noqa: E402
from data_sources.opening_hours import hours_on, parse_opening_hours  # noqa: E402
from data_sources.travel import minutes_from_osrm  # noqa: E402
from data_sources.weather import weather_for  # noqa: E402


def test_opening_hours():
    w = parse_opening_hours("Tu-Fr,Su 10:00-18:00; Sa 10:00-21:00")
    assert hours_on(w, 0) is None and hours_on(w, 5) == (10.0, 21.0) and hours_on(w, 6) == (10.0, 18.0)
    w = parse_opening_hours("We, Fr, Sa 18:30-00:30")
    assert hours_on(w, 2) == (18.5, 24.0) and hours_on(w, 3) is None
    assert hours_on(parse_opening_hours("08:30-17:30"), 3) == (8.5, 17.5)
    assert hours_on(parse_opening_hours("24/7"), 6) == (0.0, 24.0)
    assert hours_on(parse_opening_hours("Mo-Fr 11:00-14:00,17:00-21:00; Sa,Su off"), 6) is None
    assert parse_opening_hours("sunrise-sunset") is None and parse_opening_hours(None) is None


def test_normalize_and_select():
    assert osm.normalize_region("台南中西區") == "臺南市中西區"
    assert osm.normalize_region("台北 大安區") == "臺北市大安區"
    assert osm.normalize_region("花蓮縣花蓮市") == "花蓮縣花蓮市"
    els = [
        {"type": "way", "id": 1, "center": {"lat": 23.0, "lon": 120.2},
         "tags": {"name": "赤崁樓", "leisure": "park", "wikidata": "Q1", "name:en": "x", "name:ja": "y"}},
        {"type": "node", "id": 2, "lat": 23.0, "lon": 120.2, "tags": {"name": "打卡牆", "tourism": "attraction"}},
        {"type": "node", "id": 3, "lat": 23.0, "lon": 120.2, "tags": {"name": "阿堂鹹粥", "amenity": "restaurant"}},
        {"type": "node", "id": 4, "lat": 23.0, "lon": 120.2, "tags": {"name": "星巴克 赤崁店", "amenity": "cafe"}},
        {"type": "node", "id": 5, "lat": 23.0, "lon": 120.2, "tags": {"name": "甘單咖啡", "amenity": "cafe"}},
    ]
    sel = osm.select_places(els, caps={"景點": 5, "美食": 5, "咖啡廳": 1})
    names = [p["name"] for p in sel]
    assert "赤崁樓" in names and "打卡牆" not in names and "阿堂鹹粥" in names
    assert names[-1] == "甘單咖啡", "連鎖店應排在後面"


def _fake_record(name, lat, lng, rating, reviews, with_pt=False):
    d = [None] * 120
    d[11], d[4], d[9], d[13] = name, [None] * 7 + [rating, reviews], [None, None, lat, lng], ["旅遊景點"]
    if with_pt:
        d[84] = [[[6, [[h, 50 + h, ""] for h in range(9, 20)]]]]
    return d


def test_parse_google_json_and_match():
    payload = ")]}'\n" + json.dumps([["q", [[None] * 14 + [_fake_record("赤崁樓", 22.9975, 120.2025, 4.3, 26274, True)]]]])
    recs = [gs.parse_record(d) for d in gs._iter_place_records(gs._strip_xssi(payload))]
    assert recs[0]["rating"] == 4.3 and recs[0]["reviews"] == 26274
    assert recs[0]["popular_times"][5][12] == 62  # 6 = 週六 → index 5
    m = gs.best_match({"name": "赤崁樓", "lat": 22.9974, "lng": 120.2024}, recs)
    assert m and m["match_distance_m"] < 50
    assert gs.best_match({"name": "赤崁樓", "lat": 23.05, "lng": 120.25}, recs) is None  # 太遠
    dom = gs.parse_dom_labels('<span aria-label="4.3 顆星 "></span><span aria-label="26,274 則評論"></span>')
    assert dom["rating"] == 4.3 and dom["reviews"] == 26274


def test_osrm_minutes():
    t = {"distance_m": [[0, 900], [900, 0]], "duration_s": [[0, 120], [120, 0]]}
    assert minutes_from_osrm(t, "步行")[0, 1] == 12  # 0.9 km ÷ 4.5 km/h = 12 分
    assert minutes_from_osrm(t, "開車")[0, 1] == 2 + config.TRANSFER_OVERHEAD_MIN["開車"]


def test_weather_fallback():
    w = weather_for(None, dt.date(2030, 1, 1))
    assert "範例" in w["source"] and 0 <= w["rain_prob"] <= 1
    hourly = {"fetched_at": "2026-11-10T10:00:00", "time": [f"2026-11-14T{h:02d}:00" for h in range(24)],
              "precipitation_probability": [10 * (h % 5) for h in range(24)], "temperature_2m": [25.0] * 24}
    w = weather_for(hourly, dt.date(2026, 11, 14))
    assert w["rain_prob"] == 0.4 and w["temp_c"] == 25.0 and "Open-Meteo" in w["source"]


def _fixture_cache() -> dict:
    """一個小型、人工的快取檔（不連網）。"""
    rng = np.random.default_rng(0)
    pool, google = [], {}
    cats = ["景點"] * 8 + ["美食"] * 8 + ["咖啡廳"] * 6
    for i, c in enumerate(cats):
        pid = f"osm_n{i}"
        pool.append({"place_id": pid, "name": f"{c}{i}", "category": c, "osm_kind": "x",
                     "lat": 22.99 + rng.normal(0, 0.003), "lng": 120.20 + rng.normal(0, 0.003),
                     "opening_hours": ["Mo-Su 08:00-21:00", None, "Tu-Su 10:00-18:00"][i % 3],
                     "indoor": c != "景點", "notability": 1.0, "wikidata": None, "osm_url": ""})
        if i % 4 != 3:
            google[pid] = {"status": "ok", "rating": round(3.6 + rng.random(), 1),
                           "reviews": int(10 ** rng.uniform(2, 4.5)), "google_name": f"{c}{i}",
                           "popular_times": None, "url": ""}
    return {"version": 3, "region_query": "測試市測試區", "region_label": "測試市測試區",
            "region": {"query": "測試市測試區", "name": "測試區", "display_name": "測試區, 測試市, 臺灣",
                       "lat": 22.99, "lng": 120.2, "bbox": [0, 0, 0, 0], "osm_type": "relation", "osm_id": 1},
            "osm_fetched_at": "2026-11-10T10:00:00", "osm_raw_count": 100, "pool": pool, "google": google,
            "google_scraped_at": "2026-11-10T10:30:00", "google_blocked": None, "selected_ids": [],
            "weather": None, "osrm": None}


def test_real_pipeline_offline_fixture():
    import pipeline
    tmp = tempfile.mkdtemp()
    old = config.CACHE_DIR
    try:
        config.CACHE_DIR = __import__("pathlib").Path(tmp)
        data = _fixture_cache()
        rd.finalize(data)
        rd.save(data)
        r = pipeline.run("測試市測試區", dt.date(2026, 11, 14), 10, 18, source="real", allow_network=False)
        assert not r.is_mock and r.plans
        assert r.info["stats"]["with_reviews"] > 0
        assert any(s.startswith("迴歸") for s in r.crowd_src), "沒有 Google 資料的地點應由迴歸推估"
        assert any("推估" in s for s in r.crowd_src)
        for p in r.plans:
            for s in p.stops:
                row = r.places.iloc[s.idx]
                assert row.open_h <= s.arrive and s.leave <= row.close_h + 1e-9
        # 週一：Tu-Su 的地點應被排除（公休）
        r2 = pipeline.run("測試市測試區", dt.date(2026, 11, 16), 10, 18, source="real", allow_network=False)
        assert len(r2.closed_today) > 0
    finally:
        config.CACHE_DIR = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_shipped_cache_offline():
    """專案附帶的臺南市中西區快取：不連網也能規劃。"""
    import pipeline
    if rd.find_cached("臺南市中西區") is None:
        return  # 尚未產生快取時略過
    r = pipeline.run("臺南市中西區", dt.date(2026, 11, 14), 10, 18, source="real", allow_network=False)
    assert not r.is_mock and len(r.plans) >= 3
    assert r.info["stats"]["with_rating"] > 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("✓", name)
    print("全部測試通過 ✅")
