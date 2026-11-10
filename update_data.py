"""更新真實資料（OSM + Google 地圖爬蟲 + Open-Meteo + OSRM），結果存在 data/cache/。

用法：
    python update_data.py --region 臺南市中西區            # 第一次：OSM + 爬 Google（約 15–25 分鐘）
    python update_data.py --region 臺南市中西區 --no-google # 只更新景點清單、天氣、路網（不爬 Google）
    python update_data.py --region 臺南市中西區 --refresh-osm --force-google  # 全部重抓
    python update_data.py --region 臺南市中西區 --weather-only               # 只更新天氣
需要安裝 Google Chrome（爬 Google 地圖用；Selenium 會自動下載 chromedriver）。
"""
import argparse
import sys

from data_sources import region_data as rd

ap = argparse.ArgumentParser(description="更新真實資料快取")
ap.add_argument("--region", default="臺南市中西區")
ap.add_argument("--no-google", action="store_true", help="不要爬 Google 地圖")
ap.add_argument("--refresh-osm", action="store_true", help="重新查詢 OpenStreetMap 候選地點")
ap.add_argument("--force-google", action="store_true", help="已經爬過的地點也重爬")
ap.add_argument("--weather-only", action="store_true", help="只更新 Open-Meteo 天氣")
a = ap.parse_args()

if a.weather_only:
    data = rd.find_cached(a.region)
    if data is None:
        sys.exit(f"沒有「{a.region}」的快取，請先執行完整更新")
    rd.refresh_weather(data)
    rd.save(data)
else:
    rd.update_region(a.region, google=not a.no_google, refresh_osm=a.refresh_osm,
                     force_google=a.force_google)
