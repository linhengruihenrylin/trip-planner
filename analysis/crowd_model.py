"""人潮預測。

1. 有熱門時段資料 → 用曲線值當基準，再用迴歸學到的「降雨係數」做天氣修正。
2. 沒有熱門時段資料 → 用線性迴歸（星等、評論數、週末、天氣、時段）直接推估。

每個類別各訓練一個 LinearRegression；時段用 sin/cos 諧波表示，
讓「線性」模型也能表現出中午、傍晚兩個尖峰。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupShuffleSplit


def _features(df: pd.DataFrame) -> pd.DataFrame:
    h = df["hour"].astype(float)
    X = pd.DataFrame({
        "rating": df["rating"],
        "log_reviews": df["log_reviews"],
        "is_weekend": df["is_weekend"],
        "rain_prob": df["rain_prob"],
        "temp_c": df["temp_c"],
        "indoor": df["indoor"],
        "rain_x_indoor": df["rain_prob"] * df["indoor"],
    })
    for k in (1, 2, 3, 4):  # 24h、12h、8h、6h 週期
        X[f"sin{k}"] = np.sin(2 * np.pi * k * h / 24)
        X[f"cos{k}"] = np.cos(2 * np.pi * k * h / 24)
    X["weekend_x_cos1"] = X["is_weekend"] * X["cos1"]
    return X


class CrowdModel:
    def __init__(self):
        self.models: dict[str, LinearRegression] = {}
        self.metrics: dict[str, dict] = {}
        self.cols: list[str] = []

    def fit(self, history: pd.DataFrame) -> "CrowdModel":
        groups = list(history.groupby("category")) + [("全部", history)]
        for cat, g in groups:
            if g.empty:
                continue
            X, y = _features(g), g["crowd"].values
            self.cols = list(X.columns)
            r2 = None
            if g["place_id"].nunique() >= 3:
                # 以「店家」分組切驗證集：模擬預測一家沒看過的店
                split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=0)
                tr, te = next(split.split(X, y, groups=g["place_id"]))
                m = LinearRegression().fit(X.iloc[tr], y[tr])
                r2 = round(float(r2_score(y[te], m.predict(X.iloc[te]))), 3)
            self.models[cat] = LinearRegression().fit(X, y)
            self.metrics[cat] = {"R2_未見過店家": r2, "樣本數": len(g), "店家數": int(g["place_id"].nunique())}
        return self

    def _model(self, category: str) -> LinearRegression:
        # 該類別店家太少（<3 家）就用「全部」模型
        if category in self.models and self.metrics[category]["店家數"] >= 3:
            return self.models[category]
        return self.models["全部"]

    def rain_coef(self, category: str, indoor: bool) -> float:
        coef = dict(zip(self.cols, self._model(category).coef_))
        return coef["rain_prob"] + (coef["rain_x_indoor"] if indoor else 0.0)

    def predict(self, place: pd.Series, hours, weekday: int, weather: dict) -> np.ndarray:
        df = pd.DataFrame({
            "hour": list(hours), "rating": place.rating, "log_reviews": np.log10(place.reviews),
            "is_weekend": int(weekday >= 5), "rain_prob": weather["rain_prob"],
            "temp_c": weather["temp_c"], "indoor": int(place.indoor),
        })
        return np.clip(self._model(place.category).predict(_features(df)), 0, 100)

    def coef_table(self) -> pd.DataFrame:
        cols = ["rating", "log_reviews", "is_weekend", "rain_prob", "temp_c", "indoor", "rain_x_indoor"]
        names = ["星等", "評論數(log)", "週末", "降雨機率", "氣溫", "室內", "降雨×室內"]
        data = {}
        for cat, m in self.models.items():
            c = dict(zip(self.cols, m.coef_))
            data[cat] = [round(c[k], 2) for k in cols]
        return pd.DataFrame(data, index=names)


def hourly_crowd(places: pd.DataFrame, profiles: dict, model: CrowdModel,
                 weekday: int, weather: dict, hist_rain_mean: float,
                 labels: dict | None = None) -> tuple[np.ndarray, list[str]]:
    """回傳 (N×24 人潮矩陣, 每家店的資料來源)。"""
    hours = np.arange(24)
    out = np.zeros((len(places), 24))
    src = []
    for i, (_, p) in enumerate(places.iterrows()):
        prof = profiles.get(p.place_id)
        if prof is not None:
            adj = model.rain_coef(p.category, bool(p.indoor)) * (weather["rain_prob"] - hist_rain_mean)
            row = np.where(prof[weekday] > 0, prof[weekday] + adj, 0)
            src.append((labels or {}).get(p.place_id, "熱門時段") + "＋天氣修正")
        else:
            row = model.predict(p, hours, weekday, weather)
            src.append("迴歸推估")
        open_mask = (hours >= int(p.open_h)) & (hours < int(np.ceil(p.close_h)))
        out[i] = np.clip(np.where(open_mask, row, 0), 0, 100)
    return out, src
