from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


DTU_LOCATION_QUERY = "Delhi Technological University"
LOCATION_VERIFY_TOKENS = ("delhi technological university", "rohini", "shahbad daulatpur")
MAX_RESULTS_PER_PROVIDER = 12
MAX_DETAIL_PAIRS = 2
CACHE_TTL_SECONDS = 180
STALE_TTL_SECONDS = 1800
REFRESH_COOLDOWN_SECONDS = 30
PROVIDER_TIMEOUT_SECONDS = 15
HEADLESS = env_bool("HEADLESS", default=False)
DEBUG_DOM = env_bool("DEBUG_DOM", default=False)
ENABLE_LIVE_INSTAMART = env_bool("ENABLE_LIVE_INSTAMART", default=False)

QUICKCOMMERCE_API_KEY = os.getenv("QUICKCOMMERCE_API_KEY")
QUICKCOMMERCE_BASE_URL = os.getenv("QUICKCOMMERCE_BASE_URL", "https://api.quickcommerceapi.com/v1/search")
DTU_LAT = float(os.getenv("DTU_LAT", "28.7500198"))
DTU_LON = float(os.getenv("DTU_LON", "77.1173218"))


