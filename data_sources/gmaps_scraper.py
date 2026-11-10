"""Google 地圖網頁爬蟲（Selenium + 無頭 Chrome）：星等、評論數、熱門時段。

⚠️ 注意
- Google 沒有提供「熱門時段」的官方 API；爬取 Google 地圖網頁 **違反 Google 服務條款**。
  本專案僅作為期末報告的學術示範：少量（每個地區約 50 個地點）、低頻率（每次間隔 4–7 秒）、結果快取，
  不重複抓取、不散布資料。
- 沒有登入時，Google 地圖會進入「部分內容（limited view）」模式：桌機版不顯示評論數與熱門時段。
  實測用「手機版瀏覽器」的 User-Agent 可以拿到 **星等與評論數**；**熱門時段只有少數地點會出現**
  （實測臺南市中西區 48 個地點中 2 個有）；有就解析（populartimes 格式，index 84），沒有就用推估曲線／迴歸。

做法：打開 `https://www.google.com/maps/search/<地點名稱 地區>`，從瀏覽器的網路紀錄取出
Google 地圖自己呼叫的 `search?tbm=map` JSON 回應來解析（比解析畫面上的文字穩定）；
JSON 解析失敗時，再退回讀取網頁上的 aria-label（例如「4.3 顆星」「26,274 則評論」）。
"""
from __future__ import annotations

import datetime as dt
import difflib
import html as htmlmod
import json
import math
import os
import random
import re
import sys
import time
import urllib.parse

import config

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


class GoogleBlocked(RuntimeError):
    """Google 顯示「異常流量」驗證頁（/sorry/），應立即停止爬取。"""


# ---------------------------------------------------------------- 瀏覽器
def make_driver():
    from selenium import webdriver

    opts = webdriver.ChromeOptions()
    binary = config.CHROME_BINARY or ("/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else "")
    if binary:
        opts.binary_location = binary
    for a in ["--headless=new", "--disable-dev-shm-usage", "--lang=zh-TW", "--window-size=430,932",
              f"--user-agent={MOBILE_UA}"]:
        opts.add_argument(a)
    if sys.platform.startswith("linux"):  # Linux 容器/伺服器需要；Mac 不需要
        opts.add_argument("--no-sandbox")
    opts.add_experimental_option("prefs", {"intl.accept_languages": "zh-TW,zh"})
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # Selenium 4 內建 Selenium Manager：會自動下載對應版本的 chromedriver（只需安裝 Google Chrome）
    return webdriver.Chrome(options=opts)


def _accept_consent(driver) -> bool:
    """歐洲等地區會先跳出 consent.google.com 同意頁；點「全部接受」。"""
    if "consent." not in driver.current_url:
        return False
    from selenium.webdriver.common.by import By
    for xp in ["//button[.//span[contains(text(),'全部接受')]]", "//button[contains(.,'全部接受')]",
               "//button[contains(.,'Accept all')]", "//form//button"]:
        btns = driver.find_elements(By.XPATH, xp)
        if btns:
            btns[0].click()
            time.sleep(3)
            return True
    return False


# ---------------------------------------------------------------- 解析
def _strip_xssi(body: str):
    body = body.strip()
    if body.startswith(")]}'"):
        body = body.split("\n", 1)[1] if "\n" in body else body[4:]
    body = body.rstrip()
    if body.endswith('/*""*/'):
        body = body[:-6]
    return json.loads(body)


def _g(d, *idx):
    try:
        for k in idx:
            d = d[k]
        return d
    except (IndexError, KeyError, TypeError):
        return None


def _iter_place_records(j):
    """在 tbm=map 回應裡找出所有「地點資料陣列」（index 11 = 名稱，index 9 = 座標）。"""
    stack = [j]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            if (len(x) > 13 and isinstance(x[11], str) and isinstance(x[9], list)
                    and len(x[9]) >= 4 and isinstance(x[9][2], (int, float))):
                yield x
                continue
            stack.extend(reversed(x))


def parse_popular_times(raw) -> list[list[float]] | None:
    """populartimes 套件使用的格式：raw[0] = [[星期(1=一…7=日), [[小時, 百分比, ...], ...]], ...]。"""
    try:
        days = raw[0]
        week = [[0.0] * 24 for _ in range(7)]
        got = False
        for day in days:
            dn = int(day[0])
            wd = (dn - 1) % 7  # 1=週一 → 0
            for hr in day[1] or []:
                h, pct = int(hr[0]), float(hr[1])
                if 0 <= h < 24:
                    week[wd][h] = pct
                    got = got or pct > 0
        return week if got else None
    except Exception:
        return None


def parse_record(d) -> dict:
    rec = {
        "name": _g(d, 11),
        "rating": _g(d, 4, 7),
        "reviews": _g(d, 4, 8),
        "lat": _g(d, 9, 2), "lng": _g(d, 9, 3),
        "categories": _g(d, 13) or [],
        "address": _g(d, 39) if isinstance(_g(d, 39), str) else None,
        "popular_times": None,
        "time_spent": None,
    }
    if _g(d, 84) is not None:
        rec["popular_times"] = parse_popular_times(_g(d, 84))
    ts = _g(d, 117, 0)
    if isinstance(ts, str):
        rec["time_spent"] = ts
    return rec


def parse_dom_labels(page_html: str) -> dict:
    """備援：從網頁 aria-label 讀出主要地點的星等、評論數與熱門時段長條。"""
    labels = [htmlmod.unescape(x) for x in re.findall(r'aria-label="([^"]*)"', page_html)]
    out = {"rating": None, "reviews": None, "popular_bars": []}
    for l in labels:
        m = re.match(r"^\s*([1-5](?:\.\d)?)\s*顆星\s*$", l)
        if m and out["rating"] is None:
            out["rating"] = float(m.group(1))
        m = re.match(r"^\s*([\d,]+)\s*則評論\s*$", l)
        if m and out["reviews"] is None:
            out["reviews"] = int(m.group(1).replace(",", ""))
        # 中文：「星期六 14 時的熱門程度為 65%」／英文：「Usually 65% busy at 2 PM.」
        m = re.search(r"(\d+)\s*%.*?(\d{1,2})\s*(?:時|點)", l) or re.search(r"(\d+)% busy at (\d{1,2})", l)
        if m and ("熱門" in l or "人潮" in l or "busy" in l):
            out["popular_bars"].append((int(m.group(2)), int(m.group(1))))
    return out


def _norm(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("台", "臺"), ("（", "("), ("）", ")")):
        s = s.replace(a, b)
    return re.sub(r"[\s()\-·・,，.。'\"]", "", s)


_GENERIC_WORDS = re.compile(r"(咖啡館|咖啡廳|咖啡店|咖啡|cafe|café|coffee|餐廳|小吃店|小吃|專賣店|料理|店|館|臺南|台南)")


def name_similarity(a: str, b: str) -> float:
    """去掉「咖啡館」「餐廳」「台南」這類通用字後再比較，避免「暖暖蛇咖啡館」對到「他她咖啡館」。"""
    a, b = _norm(a), _norm(b)
    ca, cb = _GENERIC_WORDS.sub("", a), _GENERIC_WORDS.sub("", b)
    if ca and cb:
        a, b = ca, cb
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def accept_match(osm_name: str, google_name: str, dist_m: float, n_records: int = 1) -> bool:
    """OSM 地點與 Google 結果是否為同一地點：名稱夠像，或幾乎同一位置且搜尋結果很少。"""
    if dist_m > config.SCRAPE_MATCH_MAX_M:
        return False
    sim = name_similarity(osm_name, google_name)
    return sim >= 0.5 or (dist_m <= 120 and n_records <= 3 and sim >= 0.25)


def best_match(place: dict, records: list[dict]) -> dict | None:
    best, best_s = None, 0.0
    for r in records:
        if r.get("lat") is None or not r.get("name"):
            continue
        dist = haversine_m(place["lat"], place["lng"], r["lat"], r["lng"])
        if dist > config.SCRAPE_MATCH_MAX_M:
            continue
        sim = name_similarity(place["name"], r["name"])
        s = sim - dist / 3000
        # 名稱不太像（例如 OSM「台南天壇」vs Google「台灣首廟天壇」）但搜尋只回少數結果、而且幾乎同一位置 → 也採用
        if accept_match(place["name"], r["name"], dist, len(records)) and s > best_s:
            best, best_s = dict(r, match_distance_m=round(dist), match_similarity=round(sim, 2)), s
    return best


# ---------------------------------------------------------------- 主流程
def scrape_place(driver, place: dict, region_name: str) -> dict:
    """回傳 Google 資料 dict（含 status）。"""
    now = dt.datetime.now().isoformat(timespec="seconds")
    q = f"{place['name']} {region_name}"
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(q) + "?hl=zh-TW&gl=tw"
    driver.get_log("performance")  # 清空舊紀錄
    driver.get(url)
    time.sleep(2)
    if _accept_consent(driver):
        driver.get(url)
    time.sleep(config.SCRAPE_PAGE_WAIT_SEC)
    if "/sorry/" in driver.current_url:
        raise GoogleBlocked("Google 要求驗證（異常流量），停止爬取")

    records = []
    for e in driver.get_log("performance"):
        m = json.loads(e["message"])["message"]
        if m.get("method") != "Network.responseReceived":
            continue
        u = m["params"]["response"]["url"]
        if "tbm=map" not in u and "/maps/preview/place" not in u:
            continue
        try:
            body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": m["params"]["requestId"]})["body"]
            records += [parse_record(d) for d in _iter_place_records(_strip_xssi(body))]
        except Exception:
            continue

    match = best_match(place, records)
    dom = parse_dom_labels(driver.page_source)
    out = {"status": "not_found", "query": q, "scraped_at": now, "rating": None, "reviews": None,
           "popular_times": None, "google_name": None, "categories": [], "url": driver.current_url,
           "n_results": len(records)}
    if match:
        out.update(status="ok", rating=match["rating"], reviews=match["reviews"], google_name=match["name"],
                   categories=match["categories"], popular_times=match["popular_times"],
                   match_distance_m=match["match_distance_m"], match_similarity=match["match_similarity"],
                   time_spent=match.get("time_spent"))
        # 只找到一個地點（直接進入地點頁）時，畫面上的 aria-label 就是這個地點 → 補評論數
        if out["reviews"] is None and "/maps/place/" in driver.current_url and dom["reviews"]:
            out["reviews"] = dom["reviews"]
        if out["popular_times"] is None and dom["popular_bars"]:
            out["popular_bars_today"] = dom["popular_bars"]
    return out


def scrape_places(places: list[dict], region_name: str, progress=None, should_skip=None) -> dict:
    """依序爬取；回傳 {place_id: google_dict}。遇到 Google 驗證頁就停止並回傳已完成的部分。"""
    results: dict[str, dict] = {}
    driver = make_driver()
    try:
        for i, p in enumerate(places):
            if should_skip and should_skip(p):
                continue
            try:
                results[p["place_id"]] = scrape_place(driver, p, region_name)
            except GoogleBlocked as e:
                results["_blocked"] = {"status": "blocked", "message": str(e), "at_index": i}
                break
            except Exception as e:  # 單一地點失敗不影響其他地點
                results[p["place_id"]] = {"status": "error", "message": str(e)[:200],
                                          "scraped_at": dt.datetime.now().isoformat(timespec="seconds")}
            if progress:
                progress(i + 1, len(places), p["name"], results.get(p["place_id"], {}))
            time.sleep(random.uniform(*config.SCRAPE_SLEEP_SEC))  # 低頻率
    finally:
        driver.quit()
    return results
