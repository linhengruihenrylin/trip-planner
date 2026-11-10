"""行程規劃：有時間窗的「定向越野問題」(Team Orienteering Problem with Time Windows) 簡化版。

做法：
1. 隨機化貪婪 (randomized greedy)：每一步計算所有可行下一站的
       價值 = 分數(到達時段) × 類別偏好 − λ × (移動 + 等待)時間
   從前 K 名中依價值加權隨機抽一個，直到時間用完。
2. 每種「策略」(最高分、最少人潮、美食優先…) 各跑數十次，挑該策略指標最好的一條。
3. 不同策略間去除太相似的路線（Jaccard > 0.6），輸出 3–5 套方案。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config


@dataclass
class Stop:
    idx: int
    name: str
    category: str
    arrive: float      # 小時（例如 10.5 = 10:30）
    leave: float
    travel_min: float
    wait_min: float
    crowd: float
    crowd_src: str
    score: float
    lat: float
    lng: float


@dataclass
class Plan:
    label: str
    stops: list[Stop] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(s.score for s in self.stops)

    @property
    def avg_crowd(self) -> float:
        return float(np.mean([s.crowd for s in self.stops])) if self.stops else 0.0

    @property
    def travel_total(self) -> float:
        return sum(s.travel_min for s in self.stops)

    def count(self, cat: str) -> int:
        return sum(s.category == cat for s in self.stops)

    def ids(self) -> set[int]:
        return {s.idx for s in self.stops}


STRATEGIES = {
    # 名稱: (類別偏好倍率, 人潮懲罰加成, 美食是否任何時段都可)
    "🏆 最高分路線": ({"景點": 1.0, "美食": 1.0, "咖啡廳": 1.0}, 0.0, False),
    "🌿 最少人潮路線": ({"景點": 1.0, "美食": 1.0, "咖啡廳": 1.0}, 0.6, False),
    "🍜 美食優先路線": ({"景點": 0.6, "美食": 1.8, "咖啡廳": 1.0}, 0.0, True),
    "🏛️ 文化景點路線": ({"景點": 1.7, "美食": 0.8, "咖啡廳": 0.7}, 0.0, False),
    "☕ 悠閒咖啡路線": ({"景點": 0.9, "美食": 0.9, "咖啡廳": 1.8}, 0.2, False),
}


def fmt_time(h: float) -> str:
    m = int(round(h * 60))
    return f"{m // 60:02d}:{m % 60:02d}"


class Planner:
    def __init__(self, places: pd.DataFrame, crowd: np.ndarray, crowd_src: list[str],
                 score: np.ndarray, travel: np.ndarray, start_h: float, end_h: float,
                 categories: list[str], seed: int = config.RANDOM_SEED):
        self.p = places.reset_index(drop=True)
        self.crowd, self.src, self.score, self.travel = crowd, crowd_src, score, travel
        self.start_h, self.end_h = start_h, end_h
        self.allowed = np.array([c in categories for c in self.p.category])
        self.rng = np.random.default_rng(seed)
        self.visit_h = np.array([config.VISIT_MINUTES[c] / 60 for c in self.p.category])

    # ---- 單條路線 ----
    def _meal_idx(self, h: float) -> int | None:
        for k, (a, b) in enumerate(config.MEAL_WINDOWS):
            if a <= h <= b:
                return k
        return None

    def _build(self, bias: dict, crowd_extra: float, food_anytime: bool, greedy: bool,
               first: int | None = None) -> Plan:
        t, cur, visited, stops = self.start_h, None, set(), []
        meals_done: set[int] = set()
        meal_windows = [w for w in config.MEAL_WINDOWS if w[1] > self.start_h and w[0] < self.end_h]
        while True:
            cands = []
            for j in range(len(self.p)):
                if j in visited or not self.allowed[j]:
                    continue
                row = self.p.iloc[j]
                tr = 0.0 if cur is None else self.travel[cur, j] / 60
                arrive = t + tr
                wait = max(0.0, row.open_h - arrive)
                if wait > 0.5:
                    continue
                arrive += wait
                leave = arrive + self.visit_h[j]
                if leave > min(row.close_h, self.end_h):
                    continue
                cat = row.category
                if stops and stops[-1].category == cat == "美食":
                    continue
                mk = self._meal_idx(arrive)
                if cat == "美食" and not food_anytime and meal_windows and (mk is None or mk in meals_done):
                    continue  # 一般路線：只在用餐時段吃一餐
                if cat == "咖啡廳" and (sum(s.category == "咖啡廳" for s in stops) >= 2
                                      or (stops and stops[-1].category == "咖啡廳")):
                    continue
                h = min(int(arrive), 23)
                s = self.score[j, h] - crowd_extra * self.crowd[j, h] / 100
                val = (s + 1.0) * bias.get(cat, 1.0) - 0.9 * (tr + wait)
                if cat == "美食" and mk is not None and mk not in meals_done:
                    val += 1.0  # 用餐時段還沒吃 → 優先找吃的
                cands.append((val, j, arrive, leave, tr, wait))
            if first is not None and cur is None:
                cands = [c for c in cands if c[1] == first] or cands
            if not cands:
                break
            cands.sort(reverse=True)
            if greedy:
                pick = cands[0]
            else:
                top = cands[: config.TOP_K_RANDOM]
                v = np.array([c[0] for c in top])
                prob = np.exp((v - v.max()) / 0.15)
                pick = top[self.rng.choice(len(top), p=prob / prob.sum())]
            _, j, arrive, leave, tr, wait = pick
            row = self.p.iloc[j]
            h = min(int(arrive), 23)
            stops.append(Stop(j, row["name"], row.category, arrive, leave, round(tr * 60),
                              round(wait * 60), round(float(self.crowd[j, h]), 1), self.src[j],
                              round(float(self.score[j, h]) * 100, 1), row.lat, row.lng))
            visited.add(j)
            if row.category == "美食" and (mk := self._meal_idx(arrive)) is not None:
                meals_done.add(mk)
            cur, t = j, leave
        return Plan("", stops)

    def missed_meals(self, plan: Plan) -> int:
        """停留時間涵蓋整個用餐時段，卻沒安排吃東西的次數。"""
        miss = 0
        for a, b in config.MEAL_WINDOWS:
            if self.start_h <= a and self.end_h >= b - 0.5:
                if not any(s.category == "美食" and a <= s.arrive <= b for s in plan.stops):
                    miss += 1
        return miss if "美食" in set(self.p.category[self.allowed]) else 0

    # ---- 多套方案 ----
    def plans(self, n_plans: int = 5, n_candidates: int = config.N_CANDIDATES) -> list[Plan]:
        per = max(10, n_candidates // len(STRATEGIES))
        chosen: list[Plan] = []
        pool: list[tuple[str, Plan]] = []
        for label, (bias, extra, food_any) in STRATEGIES.items():
            cands = [self._build(bias, extra, food_any, greedy=True)]
            cands += [self._build(bias, extra, food_any, greedy=False) for _ in range(per)]
            cands = [c for c in cands if len(c.stops) >= 2]
            if not cands:
                continue
            key = _strategy_key(label)
            cands.sort(key=lambda p: key(p) - 100 * self.missed_meals(p), reverse=True)
            for c in cands:
                if all(_jaccard(c.ids(), o.ids()) <= 0.6 for o in chosen):
                    c.label = label
                    chosen.append(c)
                    break
            else:
                pool.append((label, cands[0]))
        # 多樣性不足時補上隨機探索路線
        tries = 0
        while len(chosen) < n_plans and tries < 200:
            tries += 1
            c = self._build({}, 0.0, False, greedy=False)
            if len(c.stops) >= 2 and all(_jaccard(c.ids(), o.ids()) <= 0.6 for o in chosen):
                c.label = "🎲 隨機探索路線"
                chosen.append(c)
        return chosen[:n_plans]


def _strategy_key(label: str):
    if "最少人潮" in label:
        return lambda p: -p.avg_crowd + 0.02 * p.total_score
    if "美食" in label:
        return lambda p: p.count("美食") * 40 + p.total_score
    if "景點" in label:
        return lambda p: p.count("景點") * 40 + p.total_score
    if "咖啡" in label:
        return lambda p: p.count("咖啡廳") * 40 + p.total_score - p.avg_crowd * 0.3
    return lambda p: p.total_score - 0.1 * p.travel_total


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def plan_to_df(plan: Plan) -> pd.DataFrame:
    return pd.DataFrame([{
        "順序": i + 1, "地點": s.name, "類別": s.category,
        "抵達": fmt_time(s.arrive), "離開": fmt_time(s.leave),
        "交通(分)": int(s.travel_min), "預測人潮(0-100)": s.crowd,
        "人潮資料來源": s.crowd_src, "分數": s.score,
    } for i, s in enumerate(plan.stops)])


def plans_to_csv(plans: list[Plan], header: dict | None = None) -> str:
    """所有方案合併成一張表（含方案名稱），UTF-8 BOM 讓 Excel 正確顯示中文。"""
    frames = []
    for p in plans:
        d = plan_to_df(p)
        d.insert(0, "方案", p.label)
        frames.append(d)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df["預測人潮(0-100)"] = df["預測人潮(0-100)"].round(1)
    df["分數"] = df["分數"].round(2)
    return "\ufeff" + df.to_csv(index=False)


def plans_to_markdown(plans: list[Plan], header: dict | None = None) -> str:
    h = header or {}
    lines = ["# 行程方案匯出", ""]
    for k, v in h.items():
        lines.append(f"- **{k}**：{v}")
    lines.append("")
    for p in plans:
        lines += [f"## {p.label}", "",
                  f"總分 {p.total_score:.1f}｜平均人潮 {p.avg_crowd:.0f}｜站數 {len(p.stops)}｜交通總時間 {int(p.travel_total)} 分",
                  "", "路線：" + " → ".join(s.name for s in p.stops), "",
                  "| 順序 | 地點 | 類別 | 抵達 | 離開 | 交通(分) | 預測人潮 | 人潮來源 | 分數 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for i, s in enumerate(p.stops, 1):
            lines.append(f"| {i} | {s.name} | {s.category} | {fmt_time(s.arrive)} | {fmt_time(s.leave)} | "
                         f"{int(s.travel_min)} | {s.crowd:.0f} | {s.crowd_src} | {s.score:.2f} |")
        lines.append("")
    src = h.get("資料", "")
    if "範例" in src or not src:
        lines.append("> 本結果使用範例（模擬）資料，僅供示範。")
    else:
        lines.append("> 資料來源：OpenStreetMap、Google 地圖（少量爬取，僅供學術用途）、Open-Meteo、OSRM。人潮為推估值。")
    return "\n".join(lines)
