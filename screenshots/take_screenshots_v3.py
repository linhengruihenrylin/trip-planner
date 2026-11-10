# 第三版截圖（真實資料）：先啟動 streamlit（port 8501），再在 screenshots/ 目錄下執行
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1500, "height": 1400}, locale="zh-TW")
        await pg.goto("http://localhost:8501", wait_until="networkidle")
        await pg.get_by_text("在地圖上顯示").wait_for(timeout=180000)
        await pg.wait_for_timeout(9000)
        await pg.screenshot(path="07_real_data_plans.png")
        await pg.get_by_role("tab", name="📋 地點資料").click()
        await pg.wait_for_timeout(5000)
        await pg.screenshot(path="08_real_data_places.png")
        await pg.get_by_role("tab", name="🔗 相關係數分析").click()
        await pg.wait_for_timeout(5000)
        await pg.screenshot(path="09_real_data_correlation.png")
        await b.close()

asyncio.run(main())
