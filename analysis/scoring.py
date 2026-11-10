"""評分公式：S = w1·星等_標準化 + w2·log(評論數)_標準化 − w3·人潮_標準化

權重怎麼來（用相關係數佐證）：
- w3（人潮）由使用者的「怕人潮程度」a 決定。
- 剩下的 (1 − a) 分給 w1、w2。評論數和人潮高度正相關（熱門店本來就多人），
  若給評論數太高權重，等於重複計算「熱門 = 擠」。所以依
      w1 ∝ 1 − |r(星等, 人潮)|,   w2 ∝ 1 − |r(log評論數, 人潮)|
  分配：和人潮越獨立的指標，代表越「純粹的品質訊號」，權重越高。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def derive_weights(corr: dict, crowd_aversion: float) -> dict:
    a = float(np.clip(crowd_aversion, 0.0, 0.9))
    u1 = 1 - abs(corr["r_rating_crowd"])
    u2 = 1 - abs(corr["r_reviews_crowd"])
    w1 = (1 - a) * u1 / (u1 + u2)
    w2 = (1 - a) * u2 / (u1 + u2)
    return {"w1": round(w1, 3), "w2": round(w2, 3), "w3": round(a, 3)}


def _minmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    rng = x.max() - x.min()
    return (x - x.min()) / rng if rng > 0 else np.full_like(x, 0.5)


def quality_terms(places: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return _minmax(places["rating"].values), _minmax(np.log10(places["reviews"].values))


def score_matrix(places: pd.DataFrame, crowd: np.ndarray, w: dict) -> np.ndarray:
    """N×24：每家店在每個整點的分數（−w3 ~ w1+w2）。"""
    r, v = quality_terms(places)
    return (w["w1"] * r + w["w2"] * v)[:, None] - w["w3"] * (crowd / 100.0)
