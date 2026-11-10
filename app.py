"""Streamlit 介面：streamlit run app.py"""
import datetime as dt

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

import config
import pipeline
from data_sources import region_data as rd
from data_sources.places import MOCK_REGIONS
from planner.itinerary import fmt_time, plan_to_df, plans_to_csv, plans_to_markdown

st.set_page_config(page_title="人潮避開行程規劃器", page_icon="🗺️", layout="wide")

PLAN_COLORS = ["#e63946", "#2a9d8f", "#f4a261", "#457b9d", "#9b5de5", "#6c757d"]
CAT_ICON = {"景點": "university", "美食": "cutlery", "咖啡廳": "coffee"}


@st.cache_resource(show_spinner="計算中：讀取資料 → 相關係數 → 人潮預測 → 規劃行程…")
def cached_run(region, date, start_h, end_h, cats, mode, aversion, n_plans, seed, source, cache_stamp):
    # cache_stamp：快取檔更新時間，資料更新後會自動重新計算
    return pipeline.run(region, date, start_h, end_h, list(cats), mode, aversion, n_plans, seed,
                        source=source, allow_network=True)


def cache_stamp(region: str) -> str:
    d = rd.find_cached(region)
    if not d:
        return "none"
    return f"{d.get('osm_fetched_at')}|{d.get('google_scraped_at')}|{(d.get('weather') or {}).get('fetched_at')}"


def next_saturday():
    t = dt.date.today()
    return t + dt.timedelta(days=(5 - t.weekday()) % 7 or 7)


# ---------------- 側邊欄 ----------------
with st.sidebar:
    st.header("🧭 行程條件")
    source_label = st.radio("資料來源", ["真實資料", "範例資料"], horizontal=True,
                            help="真實資料：OpenStreetMap＋Google 地圖（爬蟲快取）＋Open-Meteo＋OSRM。"
                                 "範例資料：離線也能展示的模擬資料。")
    source = "real" if source_label == "真實資料" else "mock"
    if source == "real":
        cached = rd.list_cached_regions()
        region = st.text_input("地區（臺灣任一鄉鎮市區）", "臺南市中西區",
                               help="例如：臺南市中西區、臺北市大安區、高雄市鹽埕區、花蓮縣花蓮市。"
                                    "已快取：" + ("、".join(cached) if cached else "無"))
    else:
        region = st.selectbox("地區（範例資料）", list(MOCK_REGIONS),
                              help="範例資料提供兩個地區；要查其他地區請切換到「真實資料」")
    date = st.date_input("日期", next_saturday())
    c1, c2 = st.columns(2)
    start_t = c1.time_input("開始", dt.time(10, 0), step=1800)
    end_t = c2.time_input("結束", dt.time(18, 0), step=1800)
    cats = st.multiselect("偏好類型", config.CATEGORIES, default=config.CATEGORIES)
    mode = st.radio("交通方式", list(config.SPEED_KMH), horizontal=True)
    aversion = st.slider("怕人潮程度 (w3)", 0.0, 0.9, config.DEFAULT_CROWD_AVERSION, 0.05,
                         help="越高越重視避開人潮；星等與評論數的權重由相關係數自動分配剩下的比例")
    n_plans = st.slider("方案數量", 3, 5, 5)
    seed = st.number_input("隨機種子（換一批方案）", 0, 9999, config.RANDOM_SEED)

if source == "real":
    with st.sidebar:
        st.divider()
        st.subheader("🔄 真實資料")
        cd = rd.find_cached(region)
        if cd:
            stt = rd.stats(cd)
            st.caption(f"OSM 景點清單：{cd['osm_fetched_at'][:16].replace('T', ' ')}\n\n"
                       f"Google 地圖爬取：{(cd.get('google_scraped_at') or '尚未爬取')[:16].replace('T', ' ')}\n\n"
                       f"候選 {stt['selected']} 個｜有 Google 星等 {stt['with_rating']}｜評論數 {stt['with_reviews']}｜"
                       f"熱門時段 {stt['with_popular_times']}")
        else:
            st.caption("這個地區還沒有快取。第一次計算會自動抓 OSM 景點、天氣與路網（約 1 分鐘，不含 Google 星等）。")
        do_google = st.checkbox("同時爬 Google 地圖星等／評論數（較慢，約 15–25 分鐘）", value=True,
                                help="需要電腦有安裝 Google Chrome。爬蟲違反 Google 服務條款，僅供學術少量使用。")
        if st.button("更新資料", use_container_width=True):
            bar = st.progress(0.0, text="開始更新…")
            logbox = st.empty()
            lines = []

            def _log(msg):
                lines.append(str(msg))
                logbox.code("\n".join(lines[-8:]))

            def _prog(i, n, name, res):
                bar.progress(i / n, text=f"Google 地圖 {i}/{n}：{name}")
            try:
                rd.update_region(region, google=do_google, refresh_osm=cd is None, progress=_prog, log=_log)
                bar.progress(1.0, text="完成")
                st.cache_resource.clear()
                st.rerun()
            except Exception as e:
                st.error(f"更新失敗：{e}")

start_h = start_t.hour + start_t.minute / 60
end_h = end_t.hour + end_t.minute / 60
if end_h - start_h < 1 or not cats:
    st.warning("請選擇至少 1 小時的停留時間和至少一種類型。")
    st.stop()

try:
    r = cached_run(region, date, start_h, end_h, tuple(cats), mode, aversion, n_plans, int(seed), source,
                   cache_stamp(region) if source == "real" else "mock")
except Exception as e:
    st.error(f"真實資料載入失敗：{e}\n\n可以檢查網路連線、換個地區寫法（例如「臺南市中西區」），或在側邊欄切換到「範例資料」。")
    st.stop()

# ---------------- 標題列 ----------------
wd = "一二三四五六日"[date.weekday()]
st.title("🗺️ 人潮避開行程規劃器")
st.caption(f"{region}｜{date}（週{wd}）{fmt_time(start_h)}–{fmt_time(end_h)}｜{mode}")
if r.is_mock:
    st.info("📌 目前顯示的是 **範例資料**（景點座標為近似值，星等、評論數、熱門時段、天氣皆為模擬）。"
            f"目前可切換的範例地區：{'、'.join(MOCK_REGIONS)}。")
else:
    stt = r.info["stats"]
    n = len(r.places)
    msg = (f"🌐 **真實資料**：{r.info['display_name']}｜OpenStreetMap 候選 {stt['selected']} 個（當天營業 {n} 個）｜"
           f"Google 星等 {stt['with_rating']} 個、評論數 {stt['with_reviews']} 個、熱門時段 {stt['with_popular_times']} 個｜"
           f"交通：{r.info['travel_src']}")
    st.success(msg)
    if stt["with_popular_times"] < stt["selected"]:
        st.caption(f"ℹ️ Google 地圖未登入時大多數地點不提供熱門時段（本次 {stt['with_popular_times']} 個有）；其餘地點的人潮以"
                   "「類別曲線 × 真實評論數」推估，沒有 Google 資料的地點再用迴歸模型推估（詳見「報告說明」）。")
    if r.info.get("google_blocked"):
        st.warning("上次爬取時 Google 要求驗證，部分地點沒有 Google 資料。")
m1, m2, m3, m4 = st.columns(4)
m1.metric("候選地點", len(r.places))
m2.metric("降雨機率", f"{r.weather['rain_prob']:.0%}", help=f"來源：{r.weather['source']}")
m3.metric("氣溫", f"{r.weather['temp_c']}°C")
m4.metric("評分權重 w1 / w2 / w3", f"{r.weights['w1']:.2f} / {r.weights['w2']:.2f} / {r.weights['w3']:.2f}")

tab_plan, tab_crowd, tab_corr, tab_data, tab_report = st.tabs(
    ["🧳 行程方案", "👥 人潮預測", "🔗 相關係數分析", "📋 地點資料", "📝 報告說明"])

# ---------------- 行程方案 ----------------
with tab_plan:
    if not r.plans:
        st.error("找不到可行的行程，請放寬時間或類型。")
    else:
        summary = pd.DataFrame([{
            "方案": p.label, "站數": len(p.stops), "總分": round(p.total_score, 1),
            "平均人潮": round(p.avg_crowd, 1), "交通總時間(分)": int(p.travel_total),
            "景點/美食/咖啡": f"{p.count('景點')}/{p.count('美食')}/{p.count('咖啡廳')}",
        } for p in r.plans])
        st.dataframe(summary, hide_index=True, use_container_width=True)

        # 匯出
        with st.container(border=True):
            st.markdown("**📥 匯出行程（可放進期末報告）**")
            ex_pick = st.multiselect("要匯出的方案", [p.label for p in r.plans],
                                     default=[p.label for p in r.plans], key="export_pick")
            ex_plans = [p for p in r.plans if p.label in ex_pick]
            header = {"地區": region, "日期": f"{date}（週{wd}）", "時間": f"{fmt_time(start_h)}–{fmt_time(end_h)}",
                      "交通方式": mode, "權重 w1/w2/w3": f"{r.weights['w1']:.2f}/{r.weights['w2']:.2f}/{r.weights['w3']:.2f}",
                      "資料": "範例資料" if r.is_mock else "真實資料（OSM＋Google 地圖爬蟲＋Open-Meteo＋OSRM）"}
            e1, e2 = st.columns(2)
            e1.download_button("下載 CSV", plans_to_csv(ex_plans).encode("utf-8"), f"行程_{region}_{date}.csv",
                               "text/csv", disabled=not ex_plans, use_container_width=True)
            e2.download_button("下載 Markdown", plans_to_markdown(ex_plans, header).encode("utf-8"),
                               f"行程_{region}_{date}.md", "text/markdown", disabled=not ex_plans,
                               use_container_width=True)

        labels = [p.label for p in r.plans]
        pick = st.radio("在地圖上顯示", ["全部方案"] + labels, horizontal=True)
        left, right = st.columns([3, 2])
        with left:
            fmap = folium.Map(location=[r.places.lat.mean(), r.places.lng.mean()], zoom_start=15,
                              tiles="OpenStreetMap")
            fmap.fit_bounds([[r.places.lat.min(), r.places.lng.min()], [r.places.lat.max(), r.places.lng.max()]])
            for _, p in r.places.iterrows():
                folium.CircleMarker([p.lat, p.lng], radius=3, color="#999", fill=True,
                                    tooltip=f"{p['name']}（{p.category}）★{p.rating:.1f}").add_to(fmap)
            for k, plan in enumerate(r.plans):
                if pick != "全部方案" and plan.label != pick:
                    continue
                color = PLAN_COLORS[k % len(PLAN_COLORS)]
                pts = [[s.lat, s.lng] for s in plan.stops]
                folium.PolyLine(pts, color=color, weight=5 if pick != "全部方案" else 3,
                                opacity=0.85, tooltip=plan.label).add_to(fmap)
                for i, s in enumerate(plan.stops, 1):
                    html = (f"<div style='background:{color};color:white;border-radius:50%;width:24px;"
                            f"height:24px;text-align:center;line-height:24px;font-weight:bold;"
                            f"border:2px solid white'>{i}</div>")
                    folium.Marker([s.lat, s.lng], icon=folium.DivIcon(html=html, icon_size=(24, 24),
                                  icon_anchor=(12, 12)),
                                  tooltip=f"{plan.label} 第{i}站：{s.name} {fmt_time(s.arrive)} 人潮{s.crowd:.0f}"
                                  ).add_to(fmap)
            st_folium(fmap, height=560, use_container_width=True, returned_objects=[])
        with right:
            show = r.plans if pick == "全部方案" else [p for p in r.plans if p.label == pick]
            for k, plan in enumerate(show):
                with st.expander(f"{plan.label}　總分 {plan.total_score:.1f}｜平均人潮 {plan.avg_crowd:.0f}",
                                 expanded=(k == 0)):
                    df = plan_to_df(plan)
                    st.dataframe(
                        df.drop(columns=["人潮資料來源"]), hide_index=True, use_container_width=True,
                        column_config={"預測人潮(0-100)": st.column_config.ProgressColumn(
                            "預測人潮", min_value=0, max_value=100, format="%.0f")})
                    n_reg = df["人潮資料來源"].str.startswith("迴歸").sum()
                    if n_reg:
                        st.caption(f"其中 {n_reg} 站沒有熱門時段資料，人潮由迴歸模型推估。")

# ---------------- 人潮預測 ----------------
with tab_crowd:
    st.subheader(f"各地點每小時預測人潮（週{wd}，已納入天氣修正）")
    hours = list(range(7, 24))
    heat = pd.DataFrame(r.crowd[:, 7:24], index=r.places["name"], columns=[f"{h}:00" for h in hours])
    heat = heat.loc[heat.max(axis=1).sort_values(ascending=False).index]
    fig = px.imshow(heat, color_continuous_scale="YlOrRd", aspect="auto", zmin=0, zmax=100,
                    labels=dict(color="人潮"))
    fig.update_layout(height=780, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
    src = pd.Series(r.crowd_src).value_counts()
    st.caption("資料來源：" + "、".join(f"{k} {v} 家" for k, v in src.items()))

# ---------------- 相關係數 ----------------
with tab_corr:
    a, b = st.columns([1, 1])
    with a:
        st.subheader("皮爾森相關係數矩陣")
        fig = px.imshow(r.corr_matrix.round(2), text_auto=True, color_continuous_scale="RdBu_r",
                        zmin=-1, zmax=1, aspect="auto")
        fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"歷史觀測筆數：{len(r.history):,}（過去 8 週 × 每小時；"
                   f"{'天氣為 Open-Meteo 過去實際資料' if not r.is_mock else '範例天氣'}）")
    with b:
        st.subheader("各因素 vs. 人潮 的 r 值")
        st.dataframe(r.crowd_corr.style.background_gradient(cmap="RdBu_r", vmin=-1, vmax=1).format("{:.2f}"),
                     use_container_width=True)
        pc = r.place_corr
        st.markdown(f"""
**評分權重怎麼來**（店家層級，n = {pc['n_places']}）
- r(星等, 人潮) = **{pc['r_rating_crowd']:.2f}**，r(log 評論數, 人潮) = **{pc['r_reviews_crowd']:.2f}**
- 評論數和人潮相關性較高 → 有一部分是在重複計算「熱門 = 擠」，所以分到較低權重
- w1 ∝ 1−|r₁|、w2 ∝ 1−|r₂|，再乘上 (1 − 怕人潮程度)

$$S = {r.weights['w1']:.2f}\\cdot 星等_{{norm}} + {r.weights['w2']:.2f}\\cdot \\log(評論數)_{{norm}} - {r.weights['w3']:.2f}\\cdot 人潮_{{norm}}$$
""")
        st.subheader("人潮迴歸模型（缺資料時補值）")
        st.dataframe(r.model.coef_table(), use_container_width=True)
        st.caption("驗證（以沒看過的店家做測試）：" +
                   "、".join(f"{k} R²={v['R2_未見過店家']}" for k, v in r.model.metrics.items()
                            if v["R2_未見過店家"] is not None))

# ---------------- 地點資料 ----------------
with tab_data:
    d = r.places.copy()
    d["人潮資料"] = r.crowd_src
    d["營業時間"] = [f"{fmt_time(o)}–{fmt_time(c)}" for o, c in zip(d.open_h, d.close_h)]
    if r.is_mock:
        st.dataframe(d[["name", "category", "rating", "reviews", "營業時間", "indoor", "人潮資料", "lat", "lng"]]
                     .rename(columns={"name": "名稱", "category": "類別", "rating": "星等", "reviews": "評論數",
                                      "indoor": "室內", "lat": "緯度", "lng": "經度"}),
                     hide_index=True, use_container_width=True, height=700)
    else:
        info = r.info
        st.markdown(f"**{info['display_name']}**｜OSM 抓取 {info['osm_fetched_at'][:16].replace('T', ' ')}｜"
                    f"Google 爬取 {(info.get('google_scraped_at') or '尚未')[:16].replace('T', ' ')}｜"
                    f"天氣 {(info.get('weather_fetched_at') or '無')[:16].replace('T', ' ')}")
        show = pd.DataFrame({
            "名稱(OSM)": d["name"], "Google 名稱": d["google_name"], "類別": d["category"],
            "Google 星等": d["rating_raw"], "Google 評論數": d["reviews_raw"],
            "計算用星等": d["rating"].round(2), "計算用評論數": d["reviews"].round(0),
            "熱門時段": d["has_popular_times"].map({True: "有", False: "無"}),
            "營業時間(當天)": d["營業時間"], "營業時間來源": d["hours_src"], "OSM opening_hours": d["osm_hours"],
            "室內": d["indoor"], "人潮資料": d["人潮資料"], "OSM 種類": d["osm_kind"],
            "OSM": d["osm_url"], "Google 地圖": d["gmaps_url"],
        })
        st.dataframe(show, hide_index=True, use_container_width=True, height=640,
                     column_config={"OSM": st.column_config.LinkColumn(display_text="開啟"),
                                    "Google 地圖": st.column_config.LinkColumn(display_text="開啟"),
                                    "Google 評論數": st.column_config.NumberColumn(format="%d")})
        st.caption("Google 星等／評論數空白 = 爬不到或比對不到同名地點，計算時以同類別中位數補值。")
        if len(r.closed_today):
            st.markdown(f"**當天公休（依 OSM 營業時間）**：{len(r.closed_today)} 個")
            st.dataframe(r.closed_today, hide_index=True, use_container_width=True)
        if "hourly_rain" in r.weather:
            wdf = pd.DataFrame({"時": list(r.weather["hourly_rain"].keys()),
                                "降雨機率(%)": list(r.weather["hourly_rain"].values()),
                                "氣溫(°C)": [r.weather["hourly_temp"][h] for h in r.weather["hourly_rain"]]})
            st.markdown(f"**當天逐時天氣**（{r.weather['source']}）")
            st.dataframe(wdf.set_index("時").T, use_container_width=True)

# ---------------- 報告說明 ----------------
with tab_report:
    w = r.weights
    pc = r.place_corr
    if r.is_mock:
        data_source_md = f"""目前顯示的是 **範例資料** 模式（離線備援）。切換到「真實資料」即可看到真實來源。

| 資料 | 範例模式 | 真實資料模式 |
|---|---|---|
| 地點、座標、營業時間 | 範例（{'、'.join(MOCK_REGIONS)}） | OpenStreetMap（Nominatim + Overpass API） |
| Google 星等、評論數 | 示意數值 | Selenium 爬取 Google 地圖網頁（快取） |
| 每小時人潮 | 模擬曲線，約 15% 地點刻意缺資料 | Google 熱門時段（拿得到時）／類別曲線×真實評論數推估／迴歸 |
| 天氣 | 模擬 | Open-Meteo 逐時預報與過去 8 週資料 |
| 交通時間 | 直線距離估算 | OSRM 公開伺服器道路距離 |"""
        crowd_md = """有熱門時段曲線的地點，以曲線為基準再做天氣修正；約 15% 沒有曲線的地點，用星等、評論數、時段、
是否週末、降雨機率等特徵訓練的線性迴歸推估，並以「沒看過的店家」做分組驗證、回報 R²。"""
        limits_md = """- 目前為 **範例（模擬）資料**，相關係數與迴歸結果只能說明方法可行，不代表真實世界的結論。
- 交通時間以 **直線距離**估算；貪婪法不保證全域最佳解。"""
    else:
        stt = r.info["stats"]
        data_source_md = f"""本次分析地區：**{r.info['display_name']}**。所有資料都來自**免費、免金鑰、免綁信用卡**的網路公開來源：

| 資料 | 來源 | 取得方式 | 本次數量／時間 |
|---|---|---|---|
| 地點清單、座標、類別、營業時間 | OpenStreetMap | Nominatim 地理編碼 → Overpass API 查詢景點、古蹟、餐廳、咖啡廳 | 原始 {stt['osm_raw']} 筆 → 依知名度挑 {stt['pool']} 個 → 最終 {stt['selected']} 個（{r.info['osm_fetched_at'][:10]}） |
| Google 星等、評論數 | Google 地圖網頁 | Selenium 無頭 Chrome 低頻率爬取並快取 | 星等 {stt['with_rating']} 個、評論數 {stt['with_reviews']} 個（{(r.info.get('google_scraped_at') or '未爬取')[:10]}） |
| 熱門時段（每小時人潮） | Google 地圖網頁 | 同上 | {stt['with_popular_times']} 個（未登入時大多數地點拿不到） |
| 天氣（降雨機率、氣溫） | Open-Meteo | 免金鑰 API：過去 61 天 + 未來 16 天逐時資料 | {r.weather['source']} |
| 交通時間 | OSRM 公開示範伺服器 | table 服務取得道路距離矩陣 | {r.info['travel_src']} |"""
        crowd_md = f"""- **Google 熱門時段**（{stt['with_popular_times']} 個地點）：直接當作人潮基準。
- **類別曲線 × 真實評論數（推估）**：Google 在未登入狀態下大多數地點不提供熱門時段，因此對「沒有熱門時段、但有爬到評論數」的地點，
  用各類別的典型日內曲線（餐廳午晚雙峰、景點下午高峰、咖啡廳午後高峰），乘上知名度（log 評論數）與平假日倍率，
  並套用 OSM 營業時間，作為人潮基準。**這是假設性推估，不是實測人潮**。
- **迴歸推估**：連評論數都沒有爬到的地點，用其他地點的歷史觀測表訓練線性迴歸（星等、評論數、週末、降雨、氣溫、
  室內、時段諧波）來推估，並以「沒看過的店家」做分組驗證、回報 R²。
- **歷史觀測表**：人潮基準 × Open-Meteo 過去 8 週**真實天氣**（下雨時戶外人潮下降、室內上升的效果為依常識設定的假設）。
- 注意：因為推估曲線本身使用評論數，r(評論數, 人潮) 會偏高，這正是「評論數和人潮重複計算」的極端情況，
  也說明為什麼評分公式要用相關係數調低評論數的權重。"""
        limits_md = f"""- **爬取 Google 地圖網頁違反 Google 服務條款**。本專案僅為學術期末報告少量使用：每個地區約 {stt['pool']} 個地點、
  每次間隔 4–7 秒、結果快取不重複抓取、不散布原始資料。正式產品應改用付費的官方 Places API。
- Google 地圖未登入時是「部分內容」模式，**大多數地點拿不到熱門時段**（本次 {stt['with_popular_times']}/{stt['selected']} 個有），其餘人潮以推估曲線代替；網頁改版也可能讓爬蟲失效。
- 爬蟲以「名稱相似度 + 距離 ≤ {config.SCRAPE_MATCH_MAX_M} 公尺」比對 OSM 與 Google 的地點，可能比對錯誤或比對不到（以中位數補值）。
- OpenStreetMap 由志工編輯，部分地點缺營業時間（改用類別預設值）或資料過時；午休時段簡化為連續營業。
- Overpass／Nominatim／OSRM 示範伺服器都是公益服務：本專案帶有可辨識的 User-Agent、遵守 Nominatim 每秒 1 次的限制、
  每個地區只查一次並快取。OSRM 示範伺服器只有汽車路網，步行與機車時間用道路距離 ÷ 平均速度估算。
- Open-Meteo 只提供未來 16 天預報，更遠的日期改用範例天氣並在畫面上標示。
- 貪婪法不保證找到全域最佳解，但速度快，適合即時互動。"""
    st.markdown(f"""
## 研究方法說明（可直接改寫用於報告）

### 1. 研究動機
假日出遊常遇到「評價好的地方人也最多」的兩難。本系統以網路公開資料為基礎，
在使用者指定的地區與停留時間內，自動規劃多套行程，並在「口碑」與「人潮」之間取得平衡。

### 2. 資料來源
{data_source_md}

### 3. 評分公式
每個地點在每個時段的分數為：

$$S = w_1 \\cdot 星等_{{norm}} + w_2 \\cdot \\log(評論數)_{{norm}} - w_3 \\cdot 人潮_{{norm}}$$

各變數先做 0–1 標準化；評論數取對數，避免超熱門景點的評論數壓過其他因素。
本次計算的權重為 w1 = {w['w1']:.2f}、w2 = {w['w2']:.2f}、w3 = {w['w3']:.2f}。

### 4. 以皮爾森相關係數決定權重
以店家為單位（n = {pc['n_places']}），計算星等、評論數與平均人潮的皮爾森相關係數：
r(星等, 人潮) = {pc['r_rating_crowd']:.2f}，r(log 評論數, 人潮) = {pc['r_reviews_crowd']:.2f}。
若某個「正面指標」和人潮高度相關，代表它某種程度上是在重複計算「熱門＝擁擠」，
因此令 w1 ∝ 1−|r₁|、w2 ∝ 1−|r₂|，再依使用者設定的「怕人潮程度」w3 把剩下的比例分給 w1、w2，三者總和為 1。

### 5. 人潮資料與迴歸模型
{crowd_md}

### 6. 行程規劃策略
問題屬於「有時間窗的選點與排序問題」（Orienteering Problem with Time Windows）。
系統以貪婪法為主：每一步選擇「分數高、移動時間短、且抵達時仍在營業」的下一站；
再透過隨機擾動與不同目標（最高分、最少人潮、美食優先、文化景點、悠閒咖啡）產生多套方案，
最後依總分排序輸出，並檢查不重複地點、時間不倒流、營業時間內抵達。

### 7. 研究限制
{limits_md}

### 8. 未來改進
累積多週「實際」人潮資料（例如每天排程爬取或現場計數）以取代推估曲線、
以更多週的歷史資料訓練非線性模型（如隨機森林）、加入大眾運輸班次，並收集使用者回饋驗證行程品質。
""")
