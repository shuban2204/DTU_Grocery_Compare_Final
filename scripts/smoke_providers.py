"""Low-volume live provider calibration; no private APIs or hidden cart interactions."""
from __future__ import annotations

import asyncio
import logging
import os

from playwright.async_api import async_playwright

from app.providers import BlinkitProvider, InstamartProvider

QUERIES = ("Maggi", "Amul Butter", "Coca Cola", "Lays", "Milk")


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    async with async_playwright() as playwright:
        launch_options = {"headless": os.getenv("HEADLESS", "false").lower() == "true"}
        browser_channel = os.getenv("BROWSER_CHANNEL", "").strip()
        if browser_channel:
            launch_options["channel"] = browser_channel
        browser = await playwright.chromium.launch(**launch_options)
        print(f"BROWSER: {browser_channel or 'chromium'}")
        providers = []
        try:
            for provider_cls in (BlinkitProvider, InstamartProvider):
                provider = provider_cls(await browser.new_context(viewport={"width": 1440, "height": 1000}))
                providers.append(provider)
                try:
                    await provider.initialize()
                    print(f"\n{provider.name.upper()} READY")
                except Exception as exc:  # smoke output is intentionally actionable
                    state = "BLOCKED" if provider.blocked else "INITIALIZATION FAILED"
                    print(f"\n{provider.name.upper()} {state}: {exc}")
                    for label, path in provider.last_diagnostics.items():
                        print(f"  DIAGNOSTIC {label.upper()}: {path}")

            for query in QUERIES:
                print(f"\n=== {query} ===")
                ready_providers = [provider for provider in providers if provider.ready]
                results = await asyncio.gather(*(provider.search(query) for provider in ready_providers), return_exceptions=True)
                result_by_provider = dict(zip((provider.name for provider in ready_providers), results))
                for provider in providers:
                    print(provider.name.upper())
                    if not provider.ready:
                        print("  SKIPPED DUE TO INIT FAILURE")
                        continue
                    result = result_by_provider[provider.name]
                    if isinstance(result, Exception):
                        print(f"  SEARCH FAILED: {result}")
                        continue
                    if not result:
                        print("  SEARCH SUCCESS: no valid visible listings extracted")
                        continue
                    print(f"  SEARCH SUCCESS: {len(result)} listing(s)")
                    for index, item in enumerate(result, 1):
                        print(
                            f"  {index}. title={item.title} | size={item.size_text or '-'} | price={item.price or '-'} | "
                            f"mrp={item.mrp or '-'} | availability={item.availability} | sponsored={item.sponsored} | "
                            f"url={item.product_url or item.provider_id or '-'}"
                        )
        finally:
            await asyncio.gather(*(provider.close() for provider in providers), return_exceptions=True)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
