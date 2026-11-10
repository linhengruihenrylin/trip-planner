"""命令列版本。

    python cli.py --region 臺南市中西區 --date 2026-11-14 --start 10 --end 18          # 真實資料（讀快取）
    python cli.py --source mock --region 臺南中西區                                   # 範例資料
更新真實資料請用：python update_data.py --region 臺南市中西區
"""
import argparse
import datetime as dt

import pipeline
from planner.itinerary import fmt_time

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="real", choices=["real", "mock"], help="real=真實資料（快取）；mock=範例資料")
ap.add_argument("--region", default=None, help="真實資料預設 臺南市中西區；範例資料預設 臺南中西區")
ap.add_argument("--date", default=None, help="YYYY-MM-DD，預設為下一個週六")
ap.add_argument("--start", type=float, default=10)
ap.add_argument("--end", type=float, default=18)
ap.add_argument("--mode", default="步行", choices=["步行", "機車", "開車"])
ap.add_argument("--aversion", type=float, default=0.4)
ap.add_argument("--cats", default="景點,美食,咖啡廳")
ap.add_argument("--offline", action="store_true", help="不連網，只用快取")
a = ap.parse_args()
region = a.region or ("臺南市中西區" if a.source == "real" else "臺南中西區")

if a.date:
    date = dt.date.fromisoformat(a.date)
else:
    today = dt.date.today()
    date = today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)

r = pipeline.run(region, date, a.start, a.end, a.cats.split(","), a.mode, a.aversion,
                 source=a.source, allow_network=not a.offline)
wd = "一二三四五六日"[date.weekday()]
print(f"地區：{region}  日期：{date}（週{wd}）  {fmt_time(a.start)}–{fmt_time(a.end)}  交通：{a.mode}")
if r.is_mock:
    print("資料：範例資料")
else:
    s = r.info["stats"]
    print(f"資料：真實資料｜OSM 原始 {s['osm_raw']} 筆 → 候選 {s['selected']} 個（當天營業 {len(r.places)} 個）｜"
          f"Google 星等 {s['with_rating']}、評論數 {s['with_reviews']}、熱門時段 {s['with_popular_times']}｜交通：{r.info['travel_src']}")
print(f"天氣：降雨 {r.weather['rain_prob']:.0%}、{r.weather['temp_c']}°C（{r.weather['source']}）")
pc = r.place_corr
print(f"店家層級相關係數（n={pc['n_places']}）：r(星等,人潮)={pc['r_rating_crowd']:.2f}  r(log評論數,人潮)={pc['r_reviews_crowd']:.2f}")
print(f"推導權重：w1(星等)={r.weights['w1']}  w2(評論數)={r.weights['w2']}  w3(人潮)={r.weights['w3']}")
print("迴歸模型驗證：", r.model.metrics)
print()
for p in r.plans:
    print(f"{p.label}  總分 {p.total_score:.1f}｜平均人潮 {p.avg_crowd:.0f}｜交通 {p.travel_total:.0f} 分鐘")
    for i, s in enumerate(p.stops, 1):
        row = r.places.iloc[s.idx]
        star = f"★{row.rating_raw}" if not r.is_mock and row.get("rating_raw") is not None and row.rating_raw == row.rating_raw else ""
        print(f"  {i}. {fmt_time(s.arrive)}-{fmt_time(s.leave)}  {s.name}（{s.category}）{star}"
              f"  人潮 {s.crowd:.0f}  分數 {s.score:.1f}  [{s.crowd_src}]")
    print()
