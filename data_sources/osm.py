"""OpenStreetMap：Nominatim 地理編碼 + Overpass API 抓景點、餐廳、咖啡廳。

完全免費、不需要金鑰。使用規範：
- Nominatim：每秒最多 1 次請求、必須帶可辨識的 User-Agent、結果要快取（本專案存在 data/cache/）。
- Overpass：避免頻繁大量查詢；本專案每個地區只查一次並快取。
"""
from __future__ import annotations

import re
import time

import requests

import config

_CITY_FIX = [("台", "臺")]
_CITIES = ["臺北", "新北", "桃園", "臺中", "臺南", "高雄", "基隆", "新竹", "嘉義"]


def normalize_region(region: str) -> str:
    """「台南中西區」→「臺南市中西區」，方便查詢與快取命名。"""
    r = re.sub(r"\s+", "", region.strip())
    for a, b in _CITY_FIX:
        r = r.replace(a, b)
    for c in _CITIES:
        if r.startswith(c) and not r.startswith(c + "市") and not r.startswith(c + "縣") and len(r) > len(c):
            r = c + "市" + r[len(c):]
            break
    return r


def _get(url, params, timeout=30):
    r = requests.get(url, params=params, timeout=timeout,
                     headers={"User-Agent": config.HTTP_USER_AGENT, "Accept-Language": "zh-TW"})
    r.raise_for_status()
    return r.json()


def geocode(region: str) -> dict:
    """回傳 {name, display_name, lat, lng, bbox[s,n,w,e], osm_type, osm_id}；找不到拋出 KeyError。"""
    tried = []
    for q in dict.fromkeys([normalize_region(region), region.strip()]):
        res = _get(config.NOMINATIM_URL, {"q": q, "format": "jsonv2", "countrycodes": "tw",
                                          "limit": 5, "accept-language": "zh-TW"})
        time.sleep(1.1)  # Nominatim：每秒最多 1 次
        tried.append(q)
        if not res:
            continue
        best = next((x for x in res if x.get("osm_type") == "relation"
                     and x.get("category", x.get("class")) == "boundary"), res[0])
        s, n, w, e = map(float, best["boundingbox"])
        return {"query": q, "name": best.get("name") or q, "display_name": best["display_name"],
                "lat": float(best["lat"]), "lng": float(best["lon"]), "bbox": [s, n, w, e],
                "osm_type": best["osm_type"], "osm_id": int(best["osm_id"])}
    raise KeyError(f"OpenStreetMap 找不到地區：{'、'.join(tried)}（請試試「臺南市中西區」這種寫法）")


def _area_filter(geo: dict) -> tuple[str, str]:
    if geo["osm_type"] == "relation":
        return f"area({3600000000 + geo['osm_id']})->.a;", "(area.a)"
    # 不是行政區（例如某個地標）→ 用中心點半徑 1.5 km
    return "", f"(around:1500,{geo['lat']},{geo['lng']})"


def overpass_query(geo: dict) -> str:
    pre, f = _area_filter(geo)
    return f"""[out:json][timeout:90];
{pre}
(
 nwr["tourism"~"^(attraction|museum|gallery|viewpoint)$"]["name"]{f};
 nwr["historic"]["name"]{f};
 nwr["amenity"~"^(restaurant|fast_food|food_court|cafe|ice_cream)$"]["name"]{f};
 nwr["shop"~"^(bakery|confectionery|tea)$"]["name"]{f};
 nwr["leisure"="park"]["name"]["wikidata"]{f};
 nwr["amenity"="place_of_worship"]["name"]["wikidata"]{f};
 nwr["shop"="department_store"]["name"]["wikidata"]{f};
 nwr["amenity"="marketplace"]["name"]{f};
);
out center tags;"""


def fetch_overpass(geo: dict) -> list[dict]:
    q = overpass_query(geo)
    errors = []
    for attempt in range(2):
        for url in config.OVERPASS_URLS:
            try:
                r = requests.post(url, data={"data": q}, timeout=100,
                                  headers={"User-Agent": config.HTTP_USER_AGENT})
                r.raise_for_status()
                return r.json()["elements"]
            except Exception as e:  # 公開伺服器忙碌時常見 → 換下一個鏡像
                errors.append(f"{url.split('/')[2]}: {type(e).__name__}")
                time.sleep(3 + 5 * attempt)
    raise RuntimeError("Overpass API 全部鏡像都失敗：" + "；".join(errors))


# ---------------- 分類與挑選 ----------------
_FOOD = {"restaurant", "fast_food", "food_court"}
_CAFE_AMENITY = {"cafe", "ice_cream"}
_CAFE_SHOP = {"bakery", "confectionery", "tea"}
_CHAINS = re.compile(r"(麥當勞|肯德基|摩斯|漢堡王|星巴克|路易莎|85度C|50嵐|迷客夏|八方雲集|西堤|Joyfull|"
                     r"Starbucks|McDonald|KFC|Subway|必勝客|達美樂|頂呱呱|丹丹|Mister Donut|CoCo|清心|大苑子|"
                     r"可不可|茶湯會|Cama|cama|鬍鬚張|三商|爭鮮|藏壽司|壽司郎|瓦城|王品|陶板屋|石二鍋|鼎王)", re.I)
_LOCAL_FOOD = re.compile(r"(麵|粥|粿|肉圓|擔仔|米糕|豆花|冰|湯|飯|魚|蝦|捲|包|餅|羹|粽|滷|鍋燒|蚵|小吃|牛肉|豬|鱔|布丁|甜)")
_GENERIC = re.compile(r"(打卡|解說|說明|告示|廁所|停車|牆$|招牌|入口|^\d+$)")


def classify(tags: dict) -> tuple[str, str] | None:
    """回傳 (類別, OSM 種類說明)；不要的回傳 None。"""
    am, tour, shop = tags.get("amenity"), tags.get("tourism"), tags.get("shop")
    if am in _FOOD:
        return "美食", am
    if am in _CAFE_AMENITY or shop in _CAFE_SHOP:
        return "咖啡廳", am or shop
    if tour in ("attraction", "museum", "gallery", "viewpoint"):
        return "景點", tour
    if "historic" in tags:
        return "景點", "historic:" + tags["historic"]
    if tags.get("leisure") == "park":
        return "景點", "park"
    if am in ("place_of_worship", "marketplace") or shop == "department_store":
        return "景點", am or shop
    return None


def notability(tags: dict, cat: str) -> float:
    """沒有 Google 資料前，用 OSM 標籤估計「知名度」來挑候選地點。"""
    s = 0.0
    s += 3.0 if ("wikidata" in tags or "wikipedia" in tags) else 0
    s += 2.0 if tags.get("heritage") or tags.get("historic") in ("monument", "castle", "city_gate", "ruins", "memorial") else 0
    s += 1.5 if tags.get("tourism") in ("museum", "attraction") else 0
    s += 1.0 if "opening_hours" in tags else 0
    s += 0.5 if ("name:en" in tags or "name:ja" in tags) else 0
    s += 0.5 if ("website" in tags or "contact:website" in tags or "phone" in tags) else 0
    s += 0.3 if "cuisine" in tags else 0
    n_lang = sum(1 for k in tags if k.startswith("name:") and k not in ("name:zh",))
    s += min(3.0, 0.3 * n_lang)  # 有很多語言的名稱 → 國際知名
    s -= 3.0 if ("brand" in tags or "brand:wikidata" in tags or _CHAINS.search(tags.get("name", ""))) else 0  # 連鎖店
    if cat in ("美食", "咖啡廳") and _LOCAL_FOOD.search(tags.get("name", "")):
        s += 1.0  # 在地小吃、甜品
    if tags.get("cuisine") in ("taiwanese", "local", "chinese", "noodle", "rice", "dessert", "coffee_shop"):
        s += 0.5
    s -= 1.0 if tags.get("tourism") == "artwork" else 0
    s -= 0.5 if len(tags.get("name", "")) > 18 else 0
    return s


def is_indoor(tags: dict, cat: str) -> bool:
    if cat != "景點":
        return True
    return tags.get("tourism") in ("museum", "gallery") or tags.get("building") not in (None, "no")


def select_places(elements: list[dict], caps: dict | None = None) -> list[dict]:
    """依知名度挑出要爬 Google 的候選池（之後再依 Google 評論數縮成最終清單）。"""
    caps = caps or config.SCRAPE_POOL
    rows, seen = [], set()
    for e in elements:
        tags = e.get("tags", {})
        name = (tags.get("name:zh") or tags.get("name") or "").strip()
        if not name or _GENERIC.search(name):
            continue
        c = classify(tags)
        if c is None:
            continue
        cat, kind = c
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lng = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None:
            continue
        key = re.sub(r"[\s（）()·・\-]", "", name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "place_id": f"osm_{e['type'][0]}{e['id']}", "name": name, "category": cat, "osm_kind": kind,
            "lat": float(lat), "lng": float(lng), "opening_hours": tags.get("opening_hours"),
            "indoor": is_indoor(tags, cat), "notability": round(notability(tags, cat), 2),
            "wikidata": tags.get("wikidata"), "osm_url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
        })
    out = []
    for cat, n in caps.items():
        g = sorted([r for r in rows if r["category"] == cat], key=lambda r: (-r["notability"], r["name"]))
        out += g[:n]
    return out


def fetch_region_places(region: str) -> tuple[dict, list[dict], int]:
    """回傳 (地區資訊, 候選池, OSM 原始筆數)。"""
    geo = geocode(region)
    els = fetch_overpass(geo)
    return geo, select_places(els), len(els)
