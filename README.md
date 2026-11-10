# 🗺️ 人潮避開行程規劃器（期末專題，第三版：真實網路資料）

輸入 **地區、日期、停留時段、偏好類型**，系統會蒐集網路公開資料（OpenStreetMap 景點、Google 地圖星等與評論數、
Open-Meteo 天氣、OSRM 道路距離），用 **皮爾森相關係數** 分析影響人潮的因素、決定評分權重，並用 **線性迴歸** 補齊缺少的人潮資料，
最後規劃出 **3–5 套行程方案**（最高分 / 最少人潮 / 美食優先 / 文化景點 / 悠閒咖啡），附地圖路線。

- **不用申請任何 API 金鑰、不用綁信用卡。**
- 專案已附上 **臺南市中西區** 的真實資料快取（`data/cache/`），下載後不用爬蟲、離線也能直接展示。
- 側邊欄「資料來源」可切換 **真實資料／範例資料**；範例資料是離線備援，展示永遠不會壞。

## 🍎 Mac 執行步驟（第一次）

1. 安裝 [Python 3.10 以上](https://www.python.org/downloads/macos/)；要更新資料（爬 Google 地圖）的話，還要安裝 [Google Chrome](https://www.google.com/chrome/)。
2. 解壓縮 `trip_planner_v3.zip`，打開「終端機」，輸入 `cd `（後面有空格），把 `trip_planner` 資料夾拖進視窗，按 Enter。
3. 依序輸入：

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m streamlit run app.py
```

瀏覽器會自動打開 <http://localhost:8501>。之後再開只需要：`cd` 到資料夾 → `source venv/bin/activate` → `python3 -m streamlit run app.py`。
關閉：在終端機按 `Control + C`。

> Windows：把 `python3` 換成 `python`，`source venv/bin/activate` 換成 `venv\Scripts\activate`。

## 🔄 更新資料／換地區

**網頁介面**：側邊欄選「真實資料」，在「地區」輸入任何臺灣鄉鎮市區（例如 `臺北市大安區`、`高雄市鹽埕區`、`花蓮縣花蓮市`）。
- 沒有快取的地區：第一次計算會自動抓 OSM 景點、天氣與路網（約 1 分鐘），這時還沒有 Google 星等（用中位數補值）。
- 按側邊欄的 **「更新資料」**（勾選「同時爬 Google 地圖」）就會爬 Google 星等與評論數，約 48 個地點、**15–25 分鐘**（每個地點約 20–30 秒），完成後自動重新計算。

**終端機**（啟用 venv 後）：

```bash
python3 update_data.py --region 臺南市中西區                 # OSM + 爬 Google（約 15–25 分鐘；已爬過的地點會跳過）
python3 update_data.py --region 臺北市大安區                 # 新地區
python3 update_data.py --region 臺南市中西區 --no-google     # 只更新景點清單外的天氣、路網、挑選結果
python3 update_data.py --region 臺南市中西區 --weather-only  # 只更新天氣
python3 update_data.py --region 臺南市中西區 --refresh-osm --force-google   # 全部重抓
python3 cli.py --region 臺南市中西區 --date 2026-11-14 --start 10 --end 18  # 命令列印出所有方案
python3 cli.py --source mock --region 臺南中西區             # 範例資料
python3 -m pytest -q tests                                   # 測試（全部離線）
```

爬蟲需要 Google Chrome；Selenium 4 內建的 Selenium Manager 會自動下載對應版本的 chromedriver，不用另外安裝。
如果 Chrome 不在預設位置，可設定 `export TRIP_CHROME_BINARY="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`。

## 資料來源（全部免費、免金鑰）

| 資料 | 來源 | 取得方式 | 程式 |
|---|---|---|---|
| 地區範圍 | OpenStreetMap Nominatim | 地名 → 行政區邊界（每秒最多 1 次、帶 User-Agent） | `data_sources/osm.py` |
| 景點、古蹟、餐廳、咖啡廳、座標、營業時間 | OpenStreetMap Overpass API | 依「知名度」（Wikidata、多語名稱、文化資產、營業時間…）挑出約 48 個候選 | `data_sources/osm.py`、`opening_hours.py` |
| Google 星等、評論數、熱門時段 | Google 地圖網頁 | Selenium 無頭 Chrome（手機版）低頻率爬取，結果快取 | `data_sources/gmaps_scraper.py` |
| 天氣 | Open-Meteo | 逐時降雨機率與氣溫：過去 61 天（歷史觀測）＋未來 16 天（行程當天） | `data_sources/weather.py` |
| 交通時間 | OSRM 公開示範伺服器 | 道路距離矩陣；步行／機車＝道路距離 ÷ 平均速度，開車＝OSRM 時間 | `data_sources/travel.py` |

爬完後依 **Google 評論數** 從候選池留下最終 36 個地點（景點 15、美食 12、咖啡廳 9），並去除兩個 OSM 物件對到同一個 Google 地點的重複。

### ⚠️ 使用規範與倫理

- **爬取 Google 地圖網頁違反 Google 服務條款。** 本專案僅作為期末報告的學術示範：少量（每個地區約 48 個地點）、
  低頻率（每次間隔 4–7 秒）、結果快取不重複抓、不散布原始資料。正式產品應使用付費的官方 Places API。
- Google 地圖在 **未登入** 狀態下是「部分內容」模式：桌機版看不到評論數；手機版看得到星等與評論數，但 **大多數地點沒有熱門時段**（臺南市中西區 36 個地點中只有臺南孔廟、台南天壇 2 個有）。
  因此沒有熱門時段的地點，人潮基準改用「類別典型曲線 × 真實評論數」推估（報告中要說明這是推估、不是實測）。程式仍保留熱門時段解析，若 Google 之後開放即可直接使用。
- Overpass、Nominatim、OSRM 示範伺服器都是公益服務：請不要頻繁重抓，本專案每個地區只查一次並快取。
- 如果 Google 出現「異常流量」驗證頁，爬蟲會立刻停止並保存已完成的部分；**不要嘗試繞過驗證**，過一段時間再試。

## 專案架構

```
trip_planner/
├── app.py                 # Streamlit 介面（資料來源切換、更新資料按鈕、行程、人潮、相關係數、地點資料、報告說明）
├── cli.py                 # 命令列版
├── update_data.py         # 更新真實資料（OSM → Google 爬蟲 → 天氣 → OSRM → 快取）
├── pipeline.py            # 串起整個流程：資料 → 分析 → 規劃（source="real" / "mock"）
├── config.py              # 服務網址、User-Agent、爬蟲頻率、候選數量、停留時間、交通速度…
├── data/cache/            # 真實資料快取（JSON；index.json 記錄地區 → 檔案）
├── data_sources/
│   ├── osm.py             #   Nominatim + Overpass、分類、知名度挑選
│   ├── opening_hours.py   #   OSM 營業時間解析
│   ├── gmaps_scraper.py   #   Google 地圖爬蟲（Selenium）
│   ├── region_data.py     #   快取讀寫、整合成分析用表格、缺值補齊
│   ├── weather.py         #   Open-Meteo（範例模式用模擬天氣）
│   ├── travel.py          #   OSRM 距離矩陣（失敗時直線距離）
│   ├── popular_times.py   #   類別人潮曲線（推估／範例）
│   └── places.py          #   範例資料（臺南中西區、臺北大安區）
├── analysis/              # 歷史觀測表、相關係數、迴歸、評分
├── planner/itinerary.py   # 行程規劃：隨機化貪婪 + 多策略 + 去重複
├── tests/                 # test_pipeline.py（範例）、test_real_data.py（真實資料模組，全部離線）
└── screenshots/
```

## 核心方法

### 1. 評分公式

$$S = w_1\cdot 星等_{norm} + w_2\cdot \log(評論數)_{norm} - w_3\cdot 人潮_{norm}$$

- 星等、log(評論數) 做 min-max 標準化；人潮 0–100 除以 100。
- **w3** = 使用者設定的「怕人潮程度」。
- **w1、w2 由相關係數推導**：評論數和人潮高度正相關（熱門的店本來就擠），給太高權重等於重複計算。
  所以 `w1 ∝ 1−|r(星等,人潮)|`、`w2 ∝ 1−|r(log評論數,人潮)|`，再乘上 `(1−w3)`。
  和人潮越獨立的指標，越能代表「純粹的品質」，權重越高。

### 2. 人潮預測
- 有熱門時段 → 以曲線為基準，再用迴歸學到的「降雨係數」修正（下雨戶外變少、室內變多）。
- 真實資料模式：Google 未登入時不給熱門時段 → 有爬到評論數的地點用「類別曲線 × 真實評論數」推估；連評論數都沒有的地點用迴歸推估。
- 範例資料模式：約 15% 店家刻意沒有熱門時段 → 用該類別的線性迴歸直接推估。
  特徵：星等、log 評論數、週末、降雨機率、氣溫、室內、時段的 sin/cos 諧波（讓線性模型也能有午餐/晚餐雙尖峰）。
- 驗證方式：以「店家」為單位切訓練/測試集（GroupShuffleSplit），模擬預測沒看過的店，介面會顯示 R²。

### 3. 行程規劃（有時間窗的定向越野問題）
- 每一步計算所有可行下一站的價值：`(分數 + 1) × 類別偏好 − 0.9 × (移動 + 等待小時)`。
- 限制：要在營業時間內、結束前離開、等開門不超過 30 分鐘、美食只在用餐時段（美食優先路線除外）、
  不連續兩站美食或咖啡、咖啡廳最多 2 間；涵蓋整個用餐時段卻沒吃飯的路線會被扣分。
- 每種策略跑 1 次純貪婪 + 約 60 次隨機化貪婪（從前 4 名依價值加權抽樣），取該策略指標最好的一條；
  與已選路線重疊度（Jaccard）> 0.6 的會跳過，確保方案彼此不同。

## 已知限制 / 之後可以做
- 大多數地點拿不到熱門時段 → 人潮多為推估值；r(評論數, 人潮) 因推估方式而偏高（報告中可當作「重複計算」的例子討論）。
- OSM 由志工編輯，部分地點缺營業時間（改用類別預設值）；午休時段簡化為連續營業；國定假日規則忽略。
- OSM 與 Google 地點以「名稱相似度 + 距離 ≤ 600 公尺」比對，可能對錯或對不到（以同類別中位數補值）。
- Open-Meteo 只有未來 16 天預報，更遠的日期改用範例天氣並標示。
- 規劃演算法是啟發式，不保證全域最佳；可改用 OR-Tools 或模擬退火比較。

## 版本紀錄
- **第三版**：改用真實網路資料（OSM、Google 地圖爬蟲、Open-Meteo、OSRM）＋快取、任意地區輸入、更新資料按鈕／CLI、離線測試、Mac 步驟。
- **第二版**：多地區範例資料、匯出 CSV／Markdown、報告說明分頁。
- **第一版**：範例資料原型。
