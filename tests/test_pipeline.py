"""快速自我檢查：python tests/test_pipeline.py（或 pytest）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402


def test_plans_valid():
    r = pipeline.run("臺南中西區", dt.date(2026, 11, 7), 10, 18)
    assert r.is_mock and 3 <= len(r.plans) <= 5
    w = r.weights
    assert abs(w["w1"] + w["w2"] + w["w3"] - 1) < 1e-2
    for p in r.plans:
        names = [s.name for s in p.stops]
        assert len(names) == len(set(names)), "同一路線不應重複地點"
        for a, b in zip(p.stops, p.stops[1:]):
            assert b.arrive >= a.leave, "時間不可倒流"
        assert p.stops[0].arrive >= 10 and p.stops[-1].leave <= 18 + 1e-9
        for s in p.stops:
            row = r.places.iloc[s.idx]
            assert row.open_h <= s.arrive and s.leave <= row.close_h, f"{s.name} 未營業"


def test_category_filter():
    r = pipeline.run("臺南中西區", dt.date(2026, 11, 4), 13, 17, ["咖啡廳", "景點"])
    assert all(s.category != "美食" for p in r.plans for s in p.stops)


def test_taipei_region_and_export():
    from planner.itinerary import plans_to_csv, plans_to_markdown
    r = pipeline.run("臺北大安區", dt.date(2026, 11, 7), 10, 18)
    assert r.is_mock and "大安森林公園" in set(r.places["name"]) and r.plans
    csv = plans_to_csv(r.plans)
    assert "方案" in csv and r.plans[0].stops[0].name in csv
    md = plans_to_markdown(r.plans, {"地區": "臺北大安區"})
    assert md.startswith("# 行程方案匯出") and r.plans[0].label in md


def test_unknown_region_not_silent():
    try:
        pipeline.run("高雄鹽埕區", dt.date(2026, 11, 7), 10, 18)
    except KeyError:
        return
    raise AssertionError("未知地區應該報錯，而不是默默退回臺南")


if __name__ == "__main__":
    test_plans_valid(); test_category_filter(); test_taipei_region_and_export(); test_unknown_region_not_silent(); print("全部測試通過 ✅")
