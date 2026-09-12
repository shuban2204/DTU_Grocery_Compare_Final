"""
Temporary validation script for QuickCommerce API (Swiggy Instamart at DTU).
Evaluates whether QuickCommerce API returns usable live data for Delhi Technological University.

DO NOT hardcode, log, or commit the API key.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://api.quickcommerceapi.com/v1/search"
DTU_LAT = 28.7500198
DTU_LON = 77.1173218
PLATFORM = "Swiggy"


def load_env_file(filepath: Path) -> dict:
    env_vars = {}
    if not filepath.exists():
        return env_vars
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    env_vars[key] = val
    except Exception as e:
        print(f"Warning reading {filepath}: {e}", file=sys.stderr)
    return env_vars


def get_api_key() -> str:
    env = load_env_file(Path(".env"))
    key = env.get("QUICKCOMMERCE_API_KEY") or os.environ.get("QUICKCOMMERCE_API_KEY")
    if not key or not key.strip():
        print("\n[ERROR] QUICKCOMMERCE_API_KEY is missing or empty in .env", file=sys.stderr)
        print("Please ensure .env contains:", file=sys.stderr)
        print("QUICKCOMMERCE_API_KEY=<your_api_key>\n", file=sys.stderr)
        sys.exit(1)
    return key.strip()



def call_search_api(query: str, api_key: str, platform: str = PLATFORM, lat: float = DTU_LAT, lon: float = DTU_LON, timeout: int = 15):
    params = {
        "q": query,
        "platform": platform,
        "lat": str(lat),
        "lon": str(lon),
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    print(f"\nCalling: {BASE_URL}?q={query}&platform={platform}&lat={lat}&lon={lon}")
    print("Header: X-API-Key: [CONFIGURED]")

    
    req = urllib.request.Request(
        url,
        headers={
            "X-API-Key": api_key,
            "User-Agent": "DTU-Grocery-Compare/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    
    ctx = ssl.create_default_context()
    
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8", errors="replace")
            return status, content_type, body, None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, e.headers.get("Content-Type", "") if hasattr(e, "headers") else "", body, e
    except Exception as e:
        return 0, "", "", e


def inspect_products(data):
    """
    Find list of products in response regardless of exact top-level key name.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["products", "results", "items", "data"]:
            if key in data and isinstance(data[key], list):
                return data[key]
            if key in data and isinstance(data[key], dict):
                # nested data
                for subkey in ["products", "results", "items"]:
                    if subkey in data[key] and isinstance(data[key][subkey], list):
                        return data[key][subkey]
    return []


def extract_field(item, candidate_keys):
    if not isinstance(item, dict):
        return None
    for k in candidate_keys:
        if k in item and item[k] is not None:
            return item[k]
    # check nested
    for parent in ["product", "details", "item"]:
        if parent in item and isinstance(item[parent], dict):
            for k in candidate_keys:
                if k in item[parent] and item[parent][k] is not None:
                    return item[parent][k]
    return None


def print_product_diagnostics(products):
    count = len(products)
    print(f"\n--- FIRST {min(10, count)} OF {count} RETURNED PRODUCTS ---")
    for idx, p in enumerate(products[:10], start=1):
        if not isinstance(p, dict):
            print(f"{idx}. {p}")
            continue
        
        name = extract_field(p, ["name", "title", "product_name", "display_name"])
        brand = extract_field(p, ["brand", "brand_name"])
        size = extract_field(p, ["quantity", "size", "pack_size", "unit", "weight", "net_quantity"])
        mrp = extract_field(p, ["mrp", "maximum_retail_price", "original_price", "strike_price"])
        price = extract_field(p, ["offer_price", "current_price", "price", "selling_price", "final_price"])
        avail = extract_field(p, ["availability", "in_stock", "available", "is_available", "stock_status"])
        inventory = extract_field(p, ["inventory", "stock", "quantity_available"])
        deeplink = extract_field(p, ["deeplink", "product_url", "url", "link"])
        
        print(f"\n{idx}.")
        print(f"  name: {name}")
        print(f"  brand: {brand}")
        print(f"  quantity/size: {size}")
        print(f"  mrp: {mrp}")
        print(f"  offer_price/current_price: {price}")
        print(f"  availability: {avail}")
        if inventory is not None:
            print(f"  inventory: {inventory}")
        if deeplink is not None:
            print(f"  deeplink/product_url: {deeplink}")


def save_debug_response(body_text: str):
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)
    out_file = debug_dir / "quickcommerce_response.json"
    try:
        # parse and re-dump with indent if valid JSON
        data = json.loads(body_text)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(body_text)
    print(f"\n[DEBUG] Raw response saved to: {out_file}")


def evaluate_maggi_against_manual(products):
    print("\n--- TASK 4: MAGGI COMPARISON AGAINST MANUALLY OBSERVED INSTAMART VALUES ---")
    
    # Target 1: 280 g -> ₹60
    # Target 2: 420 g -> ₹80, MRP ₹90
    # Target 3: Double Masala 95 g -> ₹20
    
    found_280 = []
    found_420 = []
    found_95_dm = []
    
    for p in products:
        if not isinstance(p, dict):
            continue
        name = str(extract_field(p, ["name", "title", "product_name"]) or "").lower()
        size = str(extract_field(p, ["quantity", "size", "pack_size", "weight"]) or "").lower()
        price = extract_field(p, ["offer_price", "current_price", "price", "selling_price"])
        mrp = extract_field(p, ["mrp", "maximum_retail_price", "original_price"])
        
        full_text = f"{name} {size}"
        
        if "280" in full_text and ("maggi" in full_text or "noodle" in full_text):
            found_280.append((name, size, price, mrp))
        if "420" in full_text and ("maggi" in full_text or "noodle" in full_text):
            found_420.append((name, size, price, mrp))
        if ("95" in full_text or "double masala" in full_text) and "maggi" in full_text:
            found_95_dm.append((name, size, price, mrp))

    print("\n280 g:")
    if found_280:
        print("FOUND")
        for item in found_280:
            print(f"  Matched: {item[0]} | size: {item[1]}")
            print(f"  API price: {item[2]} (MRP: {item[3]})")
            print("  manual observed price: ₹60")
    else:
        print("NOT FOUND")
        print("  manual observed price: ₹60")

    print("\n420 g:")
    if found_420:
        print("FOUND")
        for item in found_420:
            print(f"  Matched: {item[0]} | size: {item[1]}")
            print(f"  API price: {item[2]} (MRP: {item[3]})")
            print("  manual observed price: ₹80, MRP ₹90")
    else:
        print("NOT FOUND")
        print("  manual observed price: ₹80, MRP ₹90")

    print("\n95 g Double Masala:")
    if found_95_dm:
        print("FOUND")
        for item in found_95_dm:
            print(f"  Matched: {item[0]} | size: {item[1]}")
            print(f"  API price: {item[2]} (MRP: {item[3]})")
            print("  manual observed price: ₹20")
    else:
        print("NOT FOUND")
        print("  manual observed price: ₹20")


def evaluate_coke_against_manual(products):
    print("\n--- COCA COLA COMPARISON AGAINST MANUALLY OBSERVED INSTAMART VALUES ---")
    found_750 = []
    for p in products:
        if not isinstance(p, dict):
            continue
        name = str(extract_field(p, ["name", "title", "product_name"]) or "").lower()
        size = str(extract_field(p, ["quantity", "size", "pack_size", "weight"]) or "").lower()
        price = extract_field(p, ["offer_price", "current_price", "price", "selling_price"])
        mrp = extract_field(p, ["mrp", "maximum_retail_price", "original_price"])
        full_text = f"{name} {size}"
        
        if "750" in full_text and ("coca" in full_text or "coke" in full_text):
            found_750.append((name, size, price, mrp))

    print("\n750 ml:")
    if found_750:
        print("FOUND")
        for item in found_750:
            print(f"  Matched: {item[0]} | size: {item[1]}")
            print(f"  API price: {item[2]} (MRP: {item[3]})")
            print("  manual observed price: ₹38")
    else:
        print("NOT FOUND")
        print("  manual observed price: ₹38")


def main():
    print("=" * 60)
    print("QuickCommerce API Validation (Swiggy Instamart @ DTU)")
    print("=" * 60)
    
    api_key = get_api_key()
    print("API Key loaded successfully from .env")

    
    # ------------------ QUERY 1: Maggi ------------------
    print("\n[QUERY 1] Executing search for: 'Maggi'...")
    status, content_type, body, err = call_search_api("Maggi", api_key)
    
    print(f"\nHTTP STATUS: {status}")
    print(f"RESPONSE CONTENT TYPE: {content_type}")
    
    if err or status != 200:
        print(f"[ERROR] Request failed with status {status}: {err}")
        if body:
            print(f"Response Body (truncated):\n{body[:500]}")
            save_debug_response(body)
        sys.exit(1)
        
    try:
        data = json.loads(body)
    except Exception as parse_err:
        print(f"[ERROR] Failed to parse JSON response: {parse_err}")
        save_debug_response(body)
        sys.exit(1)
        
    save_debug_response(body)
    
    if isinstance(data, dict):
        print(f"TOP-LEVEL JSON KEYS: {list(data.keys())}")
        location_meta = {k: v for k, v in data.items() if k in ["location", "store", "area", "pincode", "address", "lat", "lon", "city"]}
        if location_meta:
            print(f"LOCATION/STORE METADATA: {location_meta}")
        else:
            print("LOCATION/STORE METADATA: None at top-level")
    else:
        print(f"TOP-LEVEL TYPE: {type(data)}")
        
    products = inspect_products(data)
    print(f"NUMBER OF PRODUCTS/RESULTS: {len(products)}")
    
    if not products:
        print("[WARNING] No products found in response!")
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  Key '{k}': type={type(v)}, preview={str(v)[:150]}")
    else:
        print_product_diagnostics(products)
        evaluate_maggi_against_manual(products)
        
        # Schema analysis
        print("\n--- DETECTED SCHEMA PATHS (from first product) ---")
        first = products[0]
        if isinstance(first, dict):
            for k, v in first.items():
                print(f"  Field: '{k}' -> type: {type(v).__name__}, sample: {repr(v)[:80]}")

    # ------------------ QUERY 2: Coca Cola (if Maggi succeeded) ------------------
    print("\n" + "=" * 60)
    print("[QUERY 2] Executing search for: 'Coca Cola'...")
    status2, content_type2, body2, err2 = call_search_api("Coca Cola", api_key)
    
    print(f"\nHTTP STATUS: {status2}")
    print(f"RESPONSE CONTENT TYPE: {content_type2}")
    
    if err2 or status2 != 200:
        print(f"[ERROR] Request failed with status {status2}: {err2}")
        if body2:
            print(f"Response Body (truncated):\n{body2[:500]}")
        return
        
    try:
        data2 = json.loads(body2)
    except Exception as parse_err:
        print(f"[ERROR] Failed to parse JSON response: {parse_err}")
        return
        
    products2 = inspect_products(data2)
    print(f"NUMBER OF PRODUCTS/RESULTS: {len(products2)}")
    if products2:
        print_product_diagnostics(products2)
        evaluate_coke_against_manual(products2)


if __name__ == "__main__":
    main()
