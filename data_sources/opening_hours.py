"""OpenStreetMap `opening_hours` 標籤的簡易解析器。

支援常見寫法：
    "Mo-Su 08:30-21:00"
    "Tu-Fr,Su 10:00-18:00; Sa 10:00-21:00"
    "Mo-Fr 11:00-14:00,17:00-21:00; Sa,Su off"
    "24/7"、"08:30-17:30"（沒寫星期 = 每天）、"We, Fr, Sa 18:30-00:30"（跨午夜）
不支援（回傳 None，改用類別預設值）：月份、日出日落、"PH"/"SH" 以外的特殊條件等。
"""
from __future__ import annotations

import re

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\+?$")
_DAY_TOKEN = re.compile(r"^(Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*-\s*(Mo|Tu|We|Th|Fr|Sa|Su))?$")


def _parse_days(sel: str) -> set[int] | None:
    days: set[int] = set()
    for tok in sel.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok in ("PH", "SH"):
            continue  # 國定假日規則：忽略
        m = _DAY_TOKEN.match(tok)
        if not m:
            return None
        a = DAYS.index(m.group(1))
        b = DAYS.index(m.group(2)) if m.group(2) else a
        i = a
        while True:
            days.add(i)
            if i == b:
                break
            i = (i + 1) % 7
    return days


def _parse_times(s: str) -> list[tuple[float, float]] | None:
    spans = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = _TIME.match(tok)
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        o, c = h1 + m1 / 60, h2 + m2 / 60
        if c <= o:  # 跨午夜，例如 18:30-00:30
            c = 24.0
        spans.append((o, min(c, 24.0)))
    return spans


def parse_opening_hours(text: str | None) -> dict[int, list[tuple[float, float]]] | None:
    """回傳 {星期(0=一…6=日): [(開, 關), ...]}；空 list = 公休。無法解析回傳 None。"""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if text == "24/7":
        return {d: [(0.0, 24.0)] for d in range(7)}
    week: dict[int, list[tuple[float, float]]] = {}
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        # 拆成「星期部分」與「時間部分」
        m = re.match(r"^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)(?:\s*-\s*(?:Mo|Tu|We|Th|Fr|Sa|Su))?\s*,?\s*)+)\s*(.*)$", rule)
        if m and not rule[:1].isdigit():
            day_sel, times = m.group(1), m.group(2).strip()
            days = _parse_days(day_sel)
            if days is None:
                return None
            if not days:  # 只有 PH 的規則
                continue
        else:
            days, times = set(range(7)), rule
        if times.lower() in ("off", "closed"):
            spans: list[tuple[float, float]] = []
        else:
            spans = _parse_times(times)
            if spans is None:
                return None
        for d in days:
            week[d] = spans
    return week or None


def hours_on(week: dict | None, weekday: int) -> tuple[float, float] | None:
    """某天的 (最早開門, 最晚打烊)；公休回傳 None。午休時段簡化為連續營業。"""
    if week is None:
        raise ValueError("no parsed hours")
    spans = week.get(weekday)
    if spans is None:          # 規則沒提到這天 → 視為公休
        return None
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)
