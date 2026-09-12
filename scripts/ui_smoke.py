"""Checks the local UI's controls and understandable all-provider failure state."""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
            await page.locator("#increase").click()
            assert await page.locator("#quantity").inner_text() == "2"
            await page.locator("#search-form").evaluate("form => form.requestSubmit()")
            await page.locator("#provider-status .status").first.wait_for()
            assert await page.locator("#refresh").is_visible()
            message = await page.locator("#message").inner_text()
            assert "Could not fetch live listings" in message
            print("UI smoke passed: controls and provider-unavailable message rendered.")
        finally:
            await page.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
