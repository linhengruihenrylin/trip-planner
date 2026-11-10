"""真實資料：整合 OSM + Google 地圖爬蟲 + Open-Meteo + OSRM，並快取在 data/cache/。

快取檔（每個地區一個 JSON）：
    data/cache/index.json                 地區名稱 → 快取檔
    data/cache/region_r2162125.json       例如臺南市中西區（OSM relation 2162125）

App／CLI 預設只讀快取（不會每次都去爬 Google）；按「更新資料」或執行
`python update_data.py --region 臺南市中西區` 才會重新抓取。
"""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

import config
from data_sources import osm
from data_sources.opening_hours import hours_on, parse_opening_hours
from data_sources.popular_times import estimated_profile
from data_sources.travel import fetch_osrm_table, minutes_from_osrm, travel_matrix
from data_sources.weather import fetch_open_meteo

CACHE_VERSION = 3
SRC_GOOGLE_PT = "Google 熱門時段"
SRC_EST = "類別曲線×Google評論數（推估）"
SRC_REG = "迴歸推估"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _index_path():
    return config.CACHE_DIR / "index.json"


def _load_index() -> dict:
    p = _index_path()
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def _key(region: str) -> str:
    return osm.normalize_region(region)


def find_cached(region: str) -> dict | None:
    """不連網：用地區名稱找快取。"""
    fn = _load_index().get(_key(region))
    if not fn:
        return None
    p = config.CACHE_DIR / fn
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def list_cached_regions() -> list[str]:
    idx = _load_index()
    return list(dict.fromkeys(idx.keys()))


def save(data: dict) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    geo = data["region"]
    fn = f"region_{geo['osm_type'][0]}{geo['osm_id']}.json"
    (config.CACHE_DIR / fn).write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    idx = _load_index()
    for k in {_key(data["region_query"]), _key(geo.get("query", "")), _key(data.get("region_label", ""))}:
        if k:
            idx[k] = fn
    _index_path().write_text(json.dumps(idx, ensure_ascii=False, indent=1), "utf-8")


# ------------------------------------------------------------------ 建立／更新
def build_osm(region: str, log=print) -> dict:
    log(f"[OSM] 查詢地區：{region}")
    geo, pool, n_raw = osm.fetch_region_places(region)
    log(f"[OSM] {geo['display_name']}：Overpass 回傳 {n_raw} 筆，依知名度挑出 {len(pool)} 個候選")
    return {"version": CACHE_VERSION, "region_query": region, "region_label": osm.normalize_region(region),
            "region": geo, "osm_fetched_at": _now(), "osm_raw_count": n_raw,
            "pool": pool, "google": {}, "google_scraped_at": None, "google_blocked": None,
            "selected_ids": [], "weather": None, "osrm": None}


def revalidate(data: dict) -> int:
    """用最新的比對規則重新檢查已快取的 Google 比對結果，不合格的標成 rejected。"""
    from data_sources.gmaps_scraper import accept_match
    by = {p["place_id"]: p for p in data["pool"]}
    n = 0
    for pid, gd in data["google"].items():
        if gd.get("status") == "ok" and pid in by:
            if not accept_match(by[pid]["name"], gd.get("google_name") or "", gd.get("match_distance_m") or 0):
                gd["status"] = "rejected_match"
                n += 1
    return n


def finalize(data: dict) -> None:
    """依 Google 評論數（有的話）+ OSM 知名度，從候選池挑出最終地點。"""
    revalidate(data)
    g = data["google"]
    sel, seen_google = [], set()

    def key(p):
        gd = g.get(p["place_id"], {})
        rev = gd.get("reviews") if gd.get("status") == "ok" else None
        return (rev is not None, math.log10(rev + 1) if rev else 0.0, p["notability"])
    for cat, n in config.MAX_PLACES.items():
        pool = [p for p in data["pool"] if p["category"] == cat]
        picked = []
        for p in sorted(pool, key=key, reverse=True):
            gd = g.get(p["place_id"], {})
            if gd.get("status") == "ok" and gd.get("google_name"):
                # 兩個 OSM 物件對到同一個 Google 地點（例如「吳園」與「原臺南公會堂」）→ 只留一個
                gk = gd["google_name"]
                if gk in seen_google:
                    continue
                seen_google.add(gk)
            picked.append(p["place_id"])
            if len(picked) >= n:
                break
        sel += picked
    data["selected_ids"] = sel


def refresh_weather(data: dict, log=print) -> bool:
    try:
        geo = data["region"]
        data["weather"] = fetch_open_meteo(geo["lat"], geo["lng"])
        log(f"[Open-Meteo] 已更新逐時天氣（{len(data['weather']['time'])} 筆）")
        return True
    except Exception as e:
        log(f"[Open-Meteo] 失敗：{e}")
        return False


def refresh_osrm(data: dict, log=print) -> bool:
    places = selected_places(data)
    try:
        t = fetch_osrm_table([p["lat"] for p in places], [p["lng"] for p in places])
        data["osrm"] = dict(t, ids=[p["place_id"] for p in places], fetched_at=_now())
        log(f"[OSRM] 已取得 {len(places)}×{len(places)} 道路距離／時間矩陣")
        return True
    except Exception as e:
        data["osrm"] = None
        log(f"[OSRM] 失敗，改用直線距離估算：{e}")
        return False


def update_region(region: str, google: bool = True, refresh_osm: bool = False, force_google: bool = False,
                  progress=None, log=print) -> dict:
    """完整更新流程：OSM → Google 爬蟲 → 挑選 → Open-Meteo → OSRM → 存檔。"""
    data = None if refresh_osm else find_cached(region)
    if data is None:
        data = build_osm(region, log)
        save(data)
    if google:
        from data_sources.gmaps_scraper import scrape_places
        revalidate(data)
        done = {k for k, v in data["google"].items() if v.get("status") == "ok"}
        todo = [p for p in data["pool"] if force_google or p["place_id"] not in done]
        log(f"[Google 地圖] 準備爬取 {len(todo)} 個地點（已快取 {len(done)} 個，每次間隔 "
            f"{config.SCRAPE_SLEEP_SEC[0]:.0f}–{config.SCRAPE_SLEEP_SEC[1]:.0f} 秒）")

        def _progress(i, n, name, res):
            log(f"  ({i}/{n}) {name}：{res.get('status')} 星等={res.get('rating')} 評論={res.get('reviews')} "
                f"熱門時段={'有' if res.get('popular_times') else '無'}")
            if progress:
                progress(i, n, name, res)

        res = scrape_places(todo, data["region_label"], progress=_progress)
        blocked = res.pop("_blocked", None)
        data["google"].update(res)
        data["google_scraped_at"] = _now()
        data["google_blocked"] = blocked
        if blocked:
            log(f"[Google 地圖] ⚠️ {blocked['message']}（已完成的部分仍會保存）")
    finalize(data)
    refresh_weather(data, log)
    refresh_osrm(data, log)
    save(data)
    log("[完成] " + json.dumps(stats(data), ensure_ascii=False))
    return data


def load_region(region: str, allow_network: bool = True, log=print) -> dict:
    """App 用：優先讀快取；沒有快取且可連網時，只抓 OSM／天氣／OSRM（不爬 Google，速度較快）。"""
    data = find_cached(region)
    if data is None:
        if not allow_network:
            raise KeyError(f"沒有「{region}」的快取資料，請先按「更新資料」或改用範例資料")
        data = build_osm(region, log)
        finalize(data)
        refresh_weather(data, log)
        refresh_osrm(data, log)
        save(data)
    return data


# ------------------------------------------------------------------ 轉成分析用表格
def selected_places(data: dict) -> list[dict]:
    by = {p["place_id"]: p for p in data["pool"]}
    ids = data.get("selected_ids") or [p["place_id"] for p in data["pool"]]
    return [by[i] for i in ids if i in by]


def stats(data: dict) -> dict:
    sel = selected_places(data)
    g = data["google"]
    ok = [g[p["place_id"]] for p in sel if g.get(p["place_id"], {}).get("status") == "ok"]
    pool_ok = [v for v in g.values() if v.get("status") == "ok"]
    return {
        "osm_raw": data.get("osm_raw_count"), "pool": len(data["pool"]), "selected": len(sel),
        "scraped": len(g), "pool_matched": len(pool_ok),
        "with_rating": sum(v.get("rating") is not None for v in ok),
        "with_reviews": sum(v.get("reviews") is not None for v in ok),
        "with_popular_times": sum(bool(v.get("popular_times")) for v in ok),
        "with_osm_hours": sum(bool(p.get("opening_hours")) for p in sel),
    }


def to_frame(data: dict, date: dt.date) -> tuple[pd.DataFrame, dict, dict, pd.DataFrame]:
    """回傳 (當天有營業的地點表, 人潮曲線 profiles, profile 來源標籤, 當天公休的地點)。"""
    wd = date.weekday()
    rows, closed = [], []
    g = data["google"]
    for p in selected_places(data):
        gd = g.get(p["place_id"], {})
        ok = gd.get("status") == "ok"
        week = parse_opening_hours(p.get("opening_hours"))
        if week is not None:
            hrs = hours_on(week, wd)
            hours_src = "OSM"
            if hrs is None:
                closed.append({"名稱": p["name"], "類別": p["category"], "OSM 營業時間": p["opening_hours"]})
                continue
        else:
            hrs, hours_src = config.DEFAULT_HOURS[p["category"]], "類別預設"
            if p["category"] == "景點" and not p["indoor"]:
                hrs = (8.0, 21.0)
        rows.append({
            "place_id": p["place_id"], "name": p["name"], "category": p["category"],
            "lat": p["lat"], "lng": p["lng"], "open_h": hrs[0], "close_h": hrs[1], "indoor": bool(p["indoor"]),
            "rating_raw": gd.get("rating") if ok else None, "reviews_raw": gd.get("reviews") if ok else None,
            "google_name": gd.get("google_name") if ok else None, "google_status": gd.get("status", "未爬取"),
            "has_popular_times": bool(ok and gd.get("popular_times")),
            "hours_src": hours_src, "osm_hours": p.get("opening_hours") or "",
            "osm_kind": p["osm_kind"], "osm_url": p["osm_url"], "gmaps_url": gd.get("url", ""),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df, {}, {}, pd.DataFrame(closed)
    # 缺值補齊：同類別中位數（沒有就用整體中位數 / 4.0、100）
    for col, fallback in (("rating_raw", 4.0), ("reviews_raw", 100.0)):
        vals = pd.to_numeric(df[col], errors="coerce")
        overall = vals.median() if vals.notna().any() else fallback
        cat_med = vals.groupby(df["category"]).transform("median").fillna(overall)
        df[col.replace("_raw", "")] = vals.fillna(cat_med).astype(float)
    df["reviews"] = df["reviews"].clip(lower=1)
    profiles, labels = {}, {}
    for _, r in df.iterrows():
        gd = g.get(r.place_id, {})
        if r.has_popular_times:
            profiles[r.place_id] = np.array(gd["popular_times"], dtype=float)
            labels[r.place_id] = SRC_GOOGLE_PT
        elif pd.notna(r.reviews_raw):
            profiles[r.place_id] = estimated_profile(r.to_dict())
            labels[r.place_id] = SRC_EST
        else:
            profiles[r.place_id] = None
            labels[r.place_id] = SRC_REG
    return df, profiles, labels, pd.DataFrame(closed)


def travel_for(data: dict, places: pd.DataFrame, mode: str) -> tuple[np.ndarray, str]:
    o = data.get("osrm")
    if o:
        pos = {pid: i for i, pid in enumerate(o["ids"])}
        if all(pid in pos for pid in places.place_id):
            idx = [pos[pid] for pid in places.place_id]
            sub = {k: np.array(o[k])[np.ix_(idx, idx)].tolist() for k in ("distance_m", "duration_s")}
            return minutes_from_osrm(sub, mode), "OSRM 道路距離"
    return travel_matrix(places.lat, places.lng, mode), "直線距離估算（OSRM 無資料）"
