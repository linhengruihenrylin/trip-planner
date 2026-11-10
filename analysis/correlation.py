"""皮爾森相關係數分析：哪些因素和人潮有關？"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_LABELS = {
    "crowd": "人潮",
    "rating": "Google 星等",
    "log_reviews": "評論數(log)",
    "is_weekend": "是否週末",
    "rain_prob": "降雨機率",
    "temp_c": "氣溫",
    "hour": "時段(小時)",
    "meal_time": "是否用餐時段",
}


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["meal_time"] = df["hour"].isin([11, 12, 13, 17, 18, 19]).astype(int)
    return df


def correlation_matrix(history: pd.DataFrame, category: str | None = None) -> pd.DataFrame:
    df = add_derived(history)
    if category:
        df = df[df["category"] == category]
    cols = list(FEATURE_LABELS)
    corr = df[cols].corr(method="pearson")
    return corr.rename(index=FEATURE_LABELS, columns=FEATURE_LABELS)


def crowd_correlations(history: pd.DataFrame) -> pd.DataFrame:
    """每個因素 vs. 人潮的 r 值（全部 + 各類別 + 室內/戶外對雨的反應）。"""
    df = add_derived(history)
    feats = [c for c in FEATURE_LABELS if c != "crowd"]
    out = {"全部": df[feats].corrwith(df["crowd"])}
    for cat, g in df.groupby("category"):
        out[cat] = g[feats].corrwith(g["crowd"])
    out["戶外"] = df[df.indoor == 0][feats].corrwith(df[df.indoor == 0]["crowd"])
    out["室內"] = df[df.indoor == 1][feats].corrwith(df[df.indoor == 1]["crowd"])
    res = pd.DataFrame(out).rename(index=FEATURE_LABELS)
    return res.round(3)


def place_level_corr(history: pd.DataFrame) -> dict:
    """店家層級：平均人潮 vs. 星等、評論數（評分公式權重會用到）。"""
    g = history.groupby("place_id").agg(crowd=("crowd", "mean"), rating=("rating", "first"),
                                        log_reviews=("log_reviews", "first"))

    def r(a, b):  # 樣本太少或某欄全相同時 r 無定義 → 回傳 0
        if len(g) < 3 or np.std(a) == 0 or np.std(b) == 0:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])
    return {
        "r_rating_crowd": r(g.rating, g.crowd),
        "r_reviews_crowd": r(g.log_reviews, g.crowd),
        "r_rating_reviews": r(g.rating, g.log_reviews),
        "n_places": len(g),
    }
