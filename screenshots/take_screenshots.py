# 截圖腳本：先啟動 streamlit（port 8501），再在 screenshots/ 目錄下執行 python take_screenshots.py
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1500, "height": 1350}, locale="zh-TW")
        await pg.goto("http://localhost:8501", wait_until="networkidle")
        await pg.get_by_text("在地圖上顯示").wait_for(timeout=60000)
        await pg.wait_for_timeout(8000)
        await pg.screenshot(path="01_plans_overview.png")
        await pg.get_by_text("🌿 最少人潮路線").last.click(); await pg.wait_for_timeout(7000)
        await pg.mouse.wheel(0, 0)
        el = pg.locator("iframe").first
        await el.scroll_into_view_if_needed(); await pg.wait_for_timeout(3000)
        await pg.screenshot(path="02_single_plan_map.png")
        await pg.get_by_role("tab", name="👥 人潮預測").click(); await pg.wait_for_timeout(4000)
        await pg.screenshot(path="03_crowd_heatmap.png")
        await pg.get_by_role("tab", name="🔗 相關係數分析").click(); await pg.wait_for_timeout(4000)
        await pg.screenshot(path="04_correlation.png")
        await b.close()
asyncio.run(main())
