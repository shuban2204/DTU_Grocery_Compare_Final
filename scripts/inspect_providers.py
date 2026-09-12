"""Temporary-safe selector aid: prints only rendered text and input attributes."""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for url in ("https://blinkit.com/", "https://www.swiggy.com/instamart"):
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(2500)
                print("\nURL:", page.url)
                print((await page.locator("body").inner_text())[:10_000])
                print("INPUTS:", await page.locator("input").evaluate_all(
                    "els => els.map(e => ({placeholder:e.placeholder, aria:e.getAttribute('aria-label'), type:e.type}))"
                ))
                await page.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
