"""Small local lifespan check for graceful provider failures, without extra HTTP deps."""
from __future__ import annotations

import asyncio

from app.main import app


async def main() -> None:
    async with app.router.lifespan_context(app):
        states = {name: "ready" if provider.ready else "unavailable" for name, provider in app.state.providers.items()}
        print({"status": "ok", "providers": states})
        response = await app.state.search_service.search("Maggi", quantity=3)
        print(response["providers"])


if __name__ == "__main__":
    asyncio.run(main())
