"""全域設定：資料來源、權重預設值、行程參數。

第三版起「真實資料」全部來自免費、免金鑰、免綁卡的公開來源：
- 景點清單／座標／營業時間：OpenStreetMap（Nominatim 地理編碼 + Overpass API）
- 天氣：Open-Meteo
- 交通時間：OSRM 公開示範伺服器
- Google 星等、評論數、熱門時段：用 Selenium 少量爬取 Google 地圖網頁（非官方，僅供學術用途）
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = Path(os.getenv("TRIP_CACHE_DIR", ROOT / "data" / "cache"))

# 公開服務要求提供可辨識的 User-Agent（Nominatim／Overpass 使用規範）
HTTP_USER_AGENT = "TripPlannerStudentProject/3.0 (academic course project; low volume)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter",
                 "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter"]
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OSRM_URL = "https://router.project-osrm.org"

# ---- 候選地點數量（爬蟲量要小）----
SCRAPE_POOL = {"景點": 18, "美食": 18, "咖啡廳": 12}  # 從 OSM 依知名度挑出、要爬 Google 的候選池
MAX_PLACES = {"景點": 15, "美食": 12, "咖啡廳": 9}    # 爬完後依 Google 評論數留下的最終候選（共 36）

# ---- Google 地圖爬蟲 ----
SCRAPE_SLEEP_SEC = (4.0, 7.0)     # 每次請求之間隨機休息幾秒（低頻率）
SCRAPE_PAGE_WAIT_SEC = 7.0        # 每頁等待載入秒數
SCRAPE_MATCH_MAX_M = 600          # Google 結果和 OSM 座標距離超過這個值就不採用
CHROME_BINARY = os.getenv("TRIP_CHROME_BINARY", "")  # 留空 = 讓 Selenium 自動找 Google Chrome

# ---- 類別 ----
CATEGORIES = ["景點", "美食", "咖啡廳"]
VISIT_MINUTES = {"景點": 60, "美食": 40, "咖啡廳": 50}  # 各類別預設停留時間
DEFAULT_HOURS = {"景點": (9.0, 18.0), "美食": (11.0, 20.0), "咖啡廳": (10.0, 20.0)}  # OSM 沒有營業時間時

# ---- 交通 ----
SPEED_KMH = {"步行": 4.5, "機車": 22.0, "開車": 18.0}  # 市區平均速度
DETOUR_FACTOR = 1.3      # 直線距離 → 實際路徑的繞路係數（OSRM 失敗時才用）
TRANSFER_OVERHEAD_MIN = {"步行": 0, "機車": 3, "開車": 8}  # 停車、找車位

# ---- 評分 ----
DEFAULT_CROWD_AVERSION = 0.4

# ---- 規劃器 ----
N_CANDIDATES = 300
TOP_K_RANDOM = 4
MEAL_WINDOWS = [(11.0, 13.5), (17.5, 19.5)]
MAX_SAME_CATEGORY_IN_ROW = 1
RANDOM_SEED = 42
