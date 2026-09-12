# DTU Grocery Compare

A local V1 assignment prototype for comparing visible Blinkit and Swiggy Instamart grocery listings at the fixed delivery location **Delhi Technological University (DTU)**.

The application uses Playwright browser automation against normal desktop pages; it does not use private APIs, reverse-engineered endpoints, logins, CAPTCHA solving, anti-bot circumvention, or cart mutation.

---

## Current Verification Status

- **Blinkit**: Live extraction is **VERIFIED and WORKING** at DTU. DTU delivery location selection, search input handling, and desktop product card extraction are verified live across acceptance queries (`Maggi`, `Amul Butter`, `Coca Cola`, `Lays`, `Milk`), returning visible titles, pack sizes, prices, MRPs, availability, and canonical product URLs.
- **Instamart Live Data Source**: Live Instamart data is provided via **`QuickCommerceInstamartProvider`** querying the third-party structured QuickCommerce API for DTU (`lat=28.7500198, lon=77.1173218`, platform `Swiggy`). This returns live catalog listings, prices, MRPs, availability, and real `swiggy.com/instamart` deeplinks without reverse-engineering private APIs or attempting anti-bot circumvention. *(QuickCommerce is an independent third-party quick-commerce data provider, not an official Swiggy partner endpoint).*
- **Quantity Bundle Consolidation**: The API returns quantity bundles as separate catalog rows (e.g. `280 g x 2`, `280 g x 4`, `750 ml x 12`). The provider automatically collapses matching rows into a single base listing with quantity offer rules (e.g. `2 for ₹65; 12 for ₹387`) compatible with the quantity pricing engine, while maintaining strict variant separation (e.g. regular Coke vs Coke Zero are never merged).
- **Graceful Snapshot Fallback**: If `QUICKCOMMERCE_API_KEY` is omitted or during API timeouts, HTTP errors, or malformed responses, the system automatically falls back to verified timestamped DTU snapshots via `InstamartSnapshotProvider`.
- **UI & API Transparency**: The UI and API clearly label data sources as `Blinkit: LIVE` and `Instamart: LIVE` (when API is configured) or `Instamart: SNAPSHOT` (when using fallback). Missing snapshots report data unavailable rather than inventing fake products.
- **Production Architecture**: Production deployments must replace automated browser scraping and manual snapshots with authorized merchant/platform partner APIs.


---

## Fresh Machine Setup & Run Guide

Follow these steps to run the application on a fresh machine (Windows, macOS, or Linux) with no prior setup.

### Prerequisites

1. **Python 3.10 or higher** installed:
   - Check with: `python --version` (or `python3 --version`).
   - If not installed, download from [python.org](https://www.python.org/downloads/) (ensure **"Add python.exe to PATH"** is checked on Windows).
2. **Internet Connection**:
   - Required during setup to download Python packages and the Playwright Chromium browser binary.
   - Required during runtime for live Blinkit DTU catalog search.

---

### Step 1: Open Terminal in Project Directory

Extract the project archive (or clone the repository) and navigate to the project root directory:

```bash
cd DTU_Grocery_Compare_Final
```

Confirm you are in the directory containing `requirements.txt`, `app/`, and `README.md`.


---

### Step 2: Create a Virtual Environment

Create an isolated Python virtual environment named `.venv`:

**Windows (PowerShell / Command Prompt):**
```bash
python -m venv .venv
```

**macOS / Linux:**
```bash
python3 -m venv .venv
```

---

### Step 3: Activate the Virtual Environment

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```
> *Tip: If PowerShell displays an execution policy error (`running scripts is disabled on this system`), run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and retry.*

**Windows (Command Prompt `cmd.exe`):**
```cmd
.venv\Scripts\activate.bat
```

**macOS / Linux (bash / zsh):**
```bash
source .venv/bin/activate
```

*(Once activated, your terminal prompt will be prefixed with `(.venv)`).*

---

### Step 4: Install Python Dependencies

Install the required packages (`FastAPI`, `Uvicorn`, `Playwright`, `RapidFuzz`, `Pydantic`, `Pytest`):

```bash
pip install -r requirements.txt
```

---

### Step 5: Install Playwright Chromium Browser

Download the dedicated Playwright Chromium browser engine (~150 MB):

```bash
playwright install chromium
```

> *Linux / WSL note: If your Linux environment lacks desktop rendering libraries, install system dependencies via:*
> ```bash
> playwright install-deps chromium
> ```

---

### Step 5b (Optional): Configure Live Instamart API Key

To enable live Swiggy Instamart catalog data at DTU via QuickCommerce API, copy `.env.exmple` to `.env` and set your key:

```bash
QUICKCOMMERCE_API_KEY=your_api_key_here
```

> **Snapshot Fallback**: If `QUICKCOMMERCE_API_KEY` is not provided, the application automatically uses verified manual DTU snapshots from `data/instamart_snapshots/` and remains completely runnable.

---

### Step 6: Start the Application

Run the FastAPI application with Uvicorn:


```bash
uvicorn app.main:app
```

- **Startup sequence**: On launch, the server initializes Blinkit and automatically selects **Delhi Technological University (DTU)** as the delivery location. Instamart snapshot data is loaded and ready immediately.
- **Default display mode**: By default, `HEADLESS=false` is set so you can visibly observe the live Blinkit browser navigate, set location, and fetch cards.
- **Headless mode**: If you prefer the browser to run silently in the background (or on a headless Linux server):
  - **Windows PowerShell**:
    ```powershell
    $env:HEADLESS="true"; uvicorn app.main:app
    ```
  - **Windows CMD**:
    ```cmd
    set HEADLESS=true && uvicorn app.main:app
    ```
  - **macOS / Linux**:
    ```bash
    HEADLESS=true uvicorn app.main:app
    ```
- **Custom Port**: If port 8000 is already in use by another application:
  ```bash
  uvicorn app.main:app --port 8001
  ```
- **Windows Note on `--reload`**: **Do NOT** pass `--reload` on Windows. `uvicorn --reload` changes Python's event loop to `WindowsSelectorEventLoop`, which prevents Playwright subprocesses from launching on Windows. Running `uvicorn app.main:app` uses `ProactorEventLoop` as required by Playwright.

---

### Step 7: Open the Web Application

Open your browser and navigate to:

**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

Try searching for any of the 5 verified acceptance queries:
- `Maggi`
- `Amul Butter`
- `Coca Cola`
- `Lays`
- `Milk`

The application displays side-by-side matches with:
- **Blinkit: LIVE** results fetched in real time at DTU.
- **Instamart: SNAPSHOT** results loaded from verified DTU snapshot files.
- Match classifications (**Exact SKU Match**, **Comparable Pack/Size**, or **Unmatched**).
- Normalized unit pricing (**₹/100 g**, **₹/100 ml**, **₹/piece**).
- Dynamic quantity pricing adjustment (**Qty: 1, 2, 4, etc.**).

---

### Step 8: Run the Automated Test Suite

Run the full deterministic test suite:

```bash
python -m pytest -q
```

**Expected output:**
```text
............................................................             [100%]
60 passed in 0.44s
```
All 60 unit and regression tests run completely offline and pass in under 1 second.

---

## Troubleshooting & FAQ

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| **PowerShell script execution disabled** | Windows default ExecutionPolicy restricts `.ps1` execution. | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in your PowerShell window, then activate `.venv`. |
| **`Executable doesn't exist at ...`** | Playwright Chromium binary is not installed yet. | Run `playwright install chromium`. |
| **`Address already in use [Errno 10048 / 98]`** | Another process is occupying port 8000. | Run on an alternative port: `uvicorn app.main:app --port 8001` (and open `http://127.0.0.1:8001`). |
| **`NotImplementedError` or event loop error on Windows** | Running `uvicorn --reload` on Windows forces `WindowsSelectorEventLoop`. | Start without reload: `uvicorn app.main:app`. |
| **Missing shared libraries on Linux/WSL** | Headless Linux distribution missing graphical/rendering packages. | Run `playwright install-deps chromium` (or `sudo playwright install-deps chromium`). |
| **Why are Instamart results marked SNAPSHOT?** | `QUICKCOMMERCE_API_KEY` is omitted from `.env`, or the third-party API is temporarily unreachable. | The application automatically falls back to verified DTU snapshots. To enable live Instamart listings, configure `QUICKCOMMERCE_API_KEY=<your_key>` in `.env`. |


---

## Optional Developer Commands

- **Provider Smoke Test Script**:
  ```bash
  python -m scripts.smoke_providers
  ```
- **Live Instamart Browser Evaluation (Optional)**:
  By default, live Instamart browser startup is disabled. To attempt live browser execution against Instamart:
  ```bash
  ENABLE_LIVE_INSTAMART=true uvicorn app.main:app
  ```
  *(Confirmed platform blocks cleanly fall back to snapshots without crashing).*

---

## Key Capabilities & Pipeline

1. **Blinkit Live Extraction**: Automates DTU location modal selection, navigates search, and parses modern desktop cards (`div[role='button'][id]`) extracting title, pack size, price, strike-through MRP, availability, and canonical slugged product URLs.
2. **Result Relevance Filtering**: Discards unrelated sponsored advertisements (e.g. popcorn, cocktail mixers, or competitor chips appearing for queries like "Maggi" or "Coca Cola") using normalized token similarity, while preserving genuine variants (e.g. Maggi Cuppa Cheesy Noodles, Coke Zero, Diet Coke).
3. **Selective Detail Enrichment**: Product detail pages are opened only when essential matching attributes (such as pack size) are missing or for ambiguous near-matches, extracting semantic label/value fields (`Pack Size`, `Unit`, `Flavour`, `Product Type`).
4. **Conservative Product Matcher**:
   - **Exact SKU Match**: Requires high title similarity, matching base units, identical parsed pack count, verified known sizes on both sides, and no variant conflicts. Unknown size can NEVER produce an exact SKU match.
   - **Variant & Brand Conflict Resolution**: Distinguishes missing variants from conflicting variants. Explicit conflicts (salted vs unsalted, Coke vs Coke Zero, Magic Masala vs Cream & Onion) reject the pair. Uncertain first tokens are not naively treated as brand mismatches.
   - **Comparable Match**: Pairs different pack sizes of the same product family and compares normalized unit price (`₹/100 g`, `₹/100 ml`, `₹/piece`).
   - **One-to-One Pairing**: Greedy selection ensures no listing is paired more than once.
5. **Instamart Dual-Source Acquisition & Bundle Consolidation**: Uses `QuickCommerceInstamartProvider` for live structured catalog queries at DTU with automatic quantity bundle consolidation (`<size> x N` -> base listing with quantity offers like `2 for ₹65; 12 for ₹387`) and strict variant separation. When the API key is unconfigured or during external API errors/timeouts, `SearchService` seamlessly falls back to developer-maintained DTU snapshots via `InstamartSnapshotProvider`.


---

## Instamart Manual Snapshots

Snapshot files in `data/instamart_snapshots/` follow this structure:
```json
{
  "query": "Maggi",
  "location": "Delhi Technological University",
  "captured_at": "2026-09-11T23:50:00+05:30",
  "source": "manual_snapshot",
  "products": [
    {
      "title": "MAGGI 2-Minute Masala Noodles",
      "size": "70 g",
      "price": "14",
      "mrp": "15",
      "product_url": null,
      "availability": "available",
      "sponsored": false
    }
  ]
}
```
Missing or unpopulated query files return `Instamart data unavailable for this query` without creating dummy products or prices.

---

## Design Document

For in-depth explanations of the system architecture, product identity matching heuristics, quantity pricing decisions, and production scaling beyond DTU, refer to **[DESIGN_NOTE.md](file:///d:/My_Files/Girnarsoft_Campus_Assignment/DESIGN_NOTE.md)**.
