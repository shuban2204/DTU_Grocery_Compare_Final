from __future__ import annotations

import logging
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright

from app.config import HEADLESS, ENABLE_LIVE_INSTAMART, QUICKCOMMERCE_API_KEY
from app.providers import BlinkitProvider, InstamartProvider, InstamartSnapshotProvider, QuickCommerceInstamartProvider
from app.providers.base import UnavailableProvider
from app.services.search_service import SearchService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    playwright = None
    browser = None
    instamart_snapshot = InstamartSnapshotProvider()
    await instamart_snapshot.initialize()

    # Preferred Instamart provider: QuickCommerce live API when configured, else snapshot
    if QUICKCOMMERCE_API_KEY and QUICKCOMMERCE_API_KEY.strip():
        instamart_preferred = QuickCommerceInstamartProvider()
        await instamart_preferred.initialize()
        logging.info("QuickCommerce live Instamart provider ready for DTU")
    else:
        instamart_preferred = instamart_snapshot
        logging.info("Instamart snapshot provider ready (QUICKCOMMERCE_API_KEY not configured)")

    providers: dict[str, Any] = {}
    try:
        loop = asyncio.get_running_loop()
        if sys.platform == "win32" and loop.__class__.__name__ == "WindowsSelectorEventLoop":
            raise RuntimeError("Windows reload event loop cannot launch Playwright; run without --reload for live browser providers.")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=HEADLESS)
        blinkit = BlinkitProvider(await browser.new_context(viewport={"width": 1440, "height": 1000}))
        try:
            await blinkit.initialize()
        except Exception as exc:
            logging.warning("Blinkit startup initialization failed: %s", exc)
        providers["blinkit"] = blinkit

        if ENABLE_LIVE_INSTAMART:
            instamart_live = InstamartProvider(await browser.new_context(viewport={"width": 1440, "height": 1000}))
            try:
                await instamart_live.initialize()
            except Exception as exc:
                logging.warning("Instamart startup initialization failed: %s", exc)
            providers["instamart"] = instamart_live
        else:
            providers["instamart"] = instamart_preferred
    except Exception as exc:
        reason = f"Browser provider unavailable: {exc.__class__.__name__}"
        logging.warning("Playwright browser startup failed: %s", exc)
        providers = {
            "blinkit": UnavailableProvider("blinkit", reason),
            "instamart": instamart_preferred,
        }
    app.state.providers = providers
    app.state.search_service = SearchService(providers, instamart_snapshot=instamart_snapshot)
    try:
        yield
    finally:
        await asyncio.gather(*(provider.close() for provider in providers.values()), return_exceptions=True)
        if instamart_preferred is not instamart_snapshot:
            await instamart_snapshot.close()

        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


app = FastAPI(title="DTU Grocery Compare", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/static/{filename}")
async def static_file(filename: str) -> FileResponse:
    # Only flat known assets are served by this small V1 application.
    if filename not in {"app.js", "styles.css"}:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC / filename)


@app.get("/api/health")
async def health(request: Request) -> dict:
    providers = request.app.state.providers
    states = {name: "ready" if provider.ready else "unavailable" for name, provider in providers.items()}
    return {"status": "ok", "providers": states}


@app.get("/api/search")
async def search(request: Request, q: str = Query(min_length=2, max_length=80), quantity: int = Query(default=1, ge=1, le=10), refresh: bool = False) -> dict:
    return await request.app.state.search_service.search(q, quantity, refresh)
