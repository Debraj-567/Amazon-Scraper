---
title: Amazon Pro Scraper
emoji: 🛒
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Amazon Product & Price Scraper

A robust, stealth Amazon product metadata and pricing scraper built with **Python**, **Selenium**, and **BeautifulSoup**, designed to mirror the architecture and anti-detection capabilities of your **Flip-Kart** automation tool.

---

##  Features

- **Interactive Web Dashboard**: Modern cyber-dark glassmorphism web UI with real-time scraping, live progress bar, metrics cards, grid/table views, and 1-click CSV/JSON export.
- **Natural Language Budget Intelligence**: Type queries like `"phones under 25k"`, `"laptops below 50000"`, or `"earbuds between 1k and 3k"`—the engine automatically extracts the budget and configures both Amazon search filters and client-side validation.
- **Strict In-Stock Filtering**: Automatically detects and eliminates out-of-stock, unavailable, or third-party unpriced items so you only get real, currently purchasable products.
- **Multi-Input Targeting**: Scrape by full Amazon URL, 10-character ASIN (`B08N5WRWNW`), search keyword, or batch text file.
- **Stealth & Anti-Bot Evasion**:
  - Reuses Chrome user profiles (`amazon_profiles/`) to persist sessions, cookies, and local delivery pincode.
  - Bypasses automation flags with `--disable-blink-features=AutomationControlled` and custom CDP `navigator.webdriver` overrides.
  - Includes Amazon CAPTCHA detection and polite random backoff delays.
- **Comprehensive Data Extraction**:
  - **ASIN & Canonical URL**
  - **Product Title**
  - **Current Price & Numeric Price**
  - **Original MRP & Discount %**
  - **Stock / Availability Status** (In Stock, Only X left, Out of stock)
  - **Ratings & Total Review Count**
  - **Brand & Seller Details** ("Sold by" & "Fulfilled by Amazon")
  - **Prime Eligibility & Delivery Time**
  - **Key Bullet Point Features**
  - **High-Resolution Product Image URL**
- **Flexible Export**: Automatically saves clean data to both `scraped_data/amazon_products.csv` and `scraped_data/amazon_products.json`.
- **Interactive CLI & Direct Command-Line Modes**.

---

##  Quick Start

### 1. Interactive Mode (Menu-driven)
Run the script without arguments to open the interactive console menu:

```bash
python main.py
```

Menu options:
```text
  1. Scrape Single Product (by URL or ASIN)
  2. Scrape Search Results (by Keyword)
  3. Scrape Batch Products from File (products.txt)
  4. Open Browser Session (to set delivery pincode / log in)
  5. View Saved Scraped Data (summary table)
  6. Toggle Headless Mode
  7. Reset Browser Profile (clear cache & cookies)
  q. Quit
```

### 2. Command-Line Arguments (Fast & Automation-friendly)

- **Scrape by ASIN**:
  ```bash
  python main.py --asin B0CHX1W1XY
  ```

- **Scrape by Full URL**:
  ```bash
  python main.py --url "https://www.amazon.in/dp/B0CHX1W1XY"
  ```

- **Scrape Search Results**:
  ```bash
  python main.py --search "mechanical keyboard" --pages 2
  ```

- **Batch Scrape from File**:
  ```bash
  python main.py --file sample_products.txt
  ```

- **Run in Headless Mode (Background)**:
  ```bash
  python main.py --asin B0CX24C6BC --headless
  ```

---

##  Project Structure

```text
Amazon/
├── amazon_scraper.py      # Core parser, search scraper, and CSV/JSON exporter
├── browser.py             # Stealth Chrome driver setup with persistent user profiles
├── main.py                # Interactive CLI and command-line entrypoint
├── scraper_config.json    # Target domain, delays, timeouts, output paths
├── sample_products.txt    # Sample ASINs ready for batch testing
└── scraped_data/          # Output directory for CSV and JSON files
    ├── amazon_products.csv
    └── amazon_products.json
```

---

##  Configuration (`scraper_config.json`)

You can customize:
- `domain`: Default `https://www.amazon.in` (can be changed to `https://www.amazon.com`).
- `delay_range_seconds`: `[2.0, 4.5]` polite random delays between requests.
- `headless`: `true` or `false`.
- `page_load_timeout`: Maximum seconds to wait for page load.
