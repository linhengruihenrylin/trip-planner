# 截圖（多地區 + 報告說明）：先啟動 streamlit（port 8501），再在 screenshots/ 目錄下執行
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1500, "height": 1350}, locale="zh-TW")
        await pg.goto("http://localhost:8501", wait_until="networkidle")
        await pg.get_by_text("在地圖上顯示").wait_for(timeout=60000)
        await pg.locator("[data-testid='stSelectbox']").first.click()
        await pg.get_by_role("option", name="臺北大安區").click()
        await pg.wait_for_timeout(4000)
        await pg.get_by_text("臺北大安區｜").first.wait_for(timeout=60000)
        await pg.wait_for_timeout(8000)
        await pg.screenshot(path="05_taipei_daan_plans.png")
        await pg.get_by_role("tab", name="📝 報告說明").click(); await pg.wait_for_timeout(4000)
        await pg.screenshot(path="06_report_tab.png")
        await b.close()
asyncio.run(main())
