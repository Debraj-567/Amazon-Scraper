#!/usr/bin/env python3
"""
Amazon Scraper CLI & Interactive Manager.
Mirrors the Flip-Kart multi-purpose tool structure with stealth Chrome automation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from amazon_scraper import AmazonScraper, DataExporter, extract_asin
from browser import get_driver, reset_profile

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "scraper_config.json"


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error reading config: {e}. Using defaults.")
    return {
        "domain": "https://www.amazon.in",
        "headless": False,
        "profiles_dir": "amazon_profiles",
        "output_dir": "scraped_data",
        "csv_file": "scraped_data/amazon_products.csv",
        "json_file": "scraped_data/amazon_products.json",
        "delay_range_seconds": [2.0, 4.0],
        "page_load_timeout": 30,
        "max_search_pages": 1,
        "stealth_mode": True,
    }


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[!] Error writing config: {e}")


def print_banner() -> None:
    banner = r"""
    ==========================================================
             AMAZON PRODUCT & PRICE SCRAPER v1.0              
        Stealth Chrome Engine with Persistent Session        
    ==========================================================
    """
    print(banner)


def show_menu() -> None:
    print("\nSelect an action:")
    print("  w. Launch Interactive Web Dashboard (Frontend)")
    print("  1. Scrape Single Product (by URL or ASIN)")
    print("  2. Scrape Search Results (by Keyword)")
    print("  3. Scrape Batch Products from File (products.txt)")
    print("  4. Open Browser Session (to set delivery pincode / log in)")
    print("  5. View Saved Scraped Data (summary table)")
    print("  6. Toggle Headless Mode (currently: {})".format(load_config().get("headless", False)))
    print("  7. Reset Browser Profile (clear cache & cookies)")
    print("  q. Quit")


def handle_scrape_single(scraper: AmazonScraper, config: Dict[str, Any]) -> None:
    target = input("\nEnter Amazon product URL or 10-character ASIN: ").strip()
    if not target:
        print("[!] Input cannot be empty.")
        return

    print(f"\n[*] Fetching product details for: {target} ...")
    data = scraper.scrape_product(target)
    if data:
        DataExporter.print_summary_card(data)
        csv_path = BASE_DIR / config.get("csv_file", "scraped_data/amazon_products.csv")
        json_path = BASE_DIR / config.get("json_file", "scraped_data/amazon_products.json")
        DataExporter.save_to_csv([data], csv_path)
        DataExporter.save_to_json([data], json_path)
    else:
        print("[x] Failed to extract product data.")


def handle_scrape_search(scraper: AmazonScraper, config: Dict[str, Any]) -> None:
    query = input("\nEnter search keyword (e.g., 'wireless earbuds'): ").strip()
    if not query:
        print("[!] Query cannot be empty.")
        return

    pages_str = input("How many result pages to scrape? [default: 1]: ").strip()
    pages = int(pages_str) if pages_str.isdigit() and int(pages_str) > 0 else 1

    print(f"\n[*] Searching Amazon for '{query}' ({pages} page(s)) ...")
    results = scraper.scrape_search_results(query, max_pages=pages)
    if results:
        print(f"\n[OK] Successfully scraped {len(results)} items!")
        for item in results[:5]:  # Preview top 5
            print(f" - [{item.get('asin')}] {item.get('title')[:45]}... | {item.get('price')} | {item.get('rating')}")
        if len(results) > 5:
            print(f"   ... and {len(results) - 5} more items.")

        csv_path = BASE_DIR / config.get("csv_file", "scraped_data/amazon_products.csv")
        json_path = BASE_DIR / config.get("json_file", "scraped_data/amazon_products.json")
        DataExporter.save_to_csv(results, csv_path)
        DataExporter.save_to_json(results, json_path)
    else:
        print("[x] No search results found.")


def handle_scrape_batch(scraper: AmazonScraper, config: Dict[str, Any]) -> None:
    default_file = BASE_DIR / "sample_products.txt"
    filepath_str = input(f"\nEnter batch file path [default: sample_products.txt]: ").strip()
    filepath = Path(filepath_str) if filepath_str else default_file

    if not filepath.exists():
        print(f"[!] File not found: {filepath}")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not lines:
        print("[!] File is empty or has no valid targets.")
        return

    print(f"\n[*] Found {len(lines)} targets to scrape in batch.")
    all_data: List[Dict[str, Any]] = []

    for idx, target in enumerate(lines, 1):
        print(f"\n--- [{idx}/{len(lines)}] Processing: {target} ---")
        item = scraper.scrape_product(target)
        if item:
            DataExporter.print_summary_card(item)
            all_data.append(item)
        else:
            print(f"[x] Failed to scrape {target}")

    if all_data:
        csv_path = BASE_DIR / config.get("csv_file", "scraped_data/amazon_products.csv")
        json_path = BASE_DIR / config.get("json_file", "scraped_data/amazon_products.json")
        DataExporter.save_to_csv(all_data, csv_path)
        DataExporter.save_to_json(all_data, json_path)
        print(f"\n[OK] Batch complete! Scraped {len(all_data)}/{len(lines)} items.")


def handle_open_browser(config: Dict[str, Any]) -> None:
    profiles_dir = BASE_DIR / config.get("profiles_dir", "amazon_profiles")
    print("\n[*] Opening interactive browser session to Amazon.in...")
    print("    You can use this window to:")
    print("    - Enter your delivery pincode on Amazon")
    print("    - Log into your account (optional, will be remembered)")
    print("    - Verify everything works")
    print("    Close the browser or press ENTER in terminal when done.")

    driver = get_driver(
        profiles_dir=profiles_dir,
        headless=False,
        user_agent=config.get("user_agent"),
        stealth=config.get("stealth_mode", True),
    )
    try:
        driver.get(config.get("domain", "https://www.amazon.in"))
        input("\n>>> Press ENTER here when you are done in the browser... ")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    print("[OK] Browser closed. Profile session saved.")


def handle_view_data(config: Dict[str, Any]) -> None:
    csv_path = BASE_DIR / config.get("csv_file", "scraped_data/amazon_products.csv")
    if not csv_path.exists():
        print("\n[!] No scraped CSV file found yet. Scrape some items first!")
        return

    try:
        df = pd.read_csv(csv_path)
        print(f"\n[OK] Loaded {len(df)} records from {csv_path.name}:")
        cols = [c for c in ["asin", "title", "price", "mrp", "discount", "rating", "availability"] if c in df.columns]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 1000)
        table_str = df[cols].tail(10).to_string(index=False)
        try:
            print(table_str)
        except UnicodeEncodeError:
            safe_str = table_str.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii", errors="replace")
            print(safe_str)
        print(f"\n(Showing up to 10 most recent entries. Full file at: {csv_path})")
    except Exception as e:
        print(f"[!] Error reading CSV: {e}")


def run_interactive(config: Dict[str, Any]) -> None:
    profiles_dir = BASE_DIR / config.get("profiles_dir", "amazon_profiles")
    headless = config.get("headless", False)

    driver = None
    scraper = None

    def ensure_scraper():
        nonlocal driver, scraper
        if driver is None:
            print("\n[*] Launching Chrome with persistent profile & anti-detection...")
            driver = get_driver(
                profiles_dir=profiles_dir,
                headless=headless,
                user_agent=config.get("user_agent"),
                stealth=config.get("stealth_mode", True),
            )
            scraper = AmazonScraper(driver, config)
        return scraper

    try:
        while True:
            show_menu()
            choice = input("\nSelect option (1-7 or q): ").strip().lower()

            if choice in ("q", "quit", "exit"):
                print("\nExiting. Goodbye!")
                break
            elif choice == "w":
                if driver:
                    driver.quit()
                    driver = None
                    scraper = None
                from web_server import run_server
                run_server(5050)
            elif choice == "1":
                s = ensure_scraper()
                handle_scrape_single(s, config)
            elif choice == "2":
                s = ensure_scraper()
                handle_scrape_search(s, config)
            elif choice == "3":
                s = ensure_scraper()
                handle_scrape_batch(s, config)
            elif choice == "4":
                if driver:
                    driver.quit()
                    driver = None
                    scraper = None
                handle_open_browser(config)
            elif choice == "5":
                handle_view_data(config)
            elif choice == "6":
                config["headless"] = not config.get("headless", False)
                save_config(config)
                print(f"[OK] Headless mode set to: {config['headless']}")
                if driver:
                    driver.quit()
                    driver = None
                    scraper = None
                    print("[*] Restarting driver on next action with new headless setting.")
            elif choice == "7":
                if driver:
                    driver.quit()
                    driver = None
                    scraper = None
                confirm = input("Are you sure you want to delete saved cookies/session? (y/N): ").strip().lower()
                if confirm == "y":
                    reset_profile(profiles_dir)
                    print("[OK] Profile reset.")
            else:
                print(f"[!] Invalid option: '{choice}'. Enter 1-7 or q.")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def run_cli_args(args: argparse.Namespace, config: Dict[str, Any]) -> None:
    profiles_dir = BASE_DIR / config.get("profiles_dir", "amazon_profiles")
    headless = args.headless if args.headless is not None else config.get("headless", False)

    csv_path = Path(args.output_csv) if args.output_csv else (BASE_DIR / config.get("csv_file", "scraped_data/amazon_products.csv"))
    json_path = Path(args.output_json) if args.output_json else (BASE_DIR / config.get("json_file", "scraped_data/amazon_products.json"))

    print("[*] Starting driver in headless=" + str(headless) + " mode...")
    driver = get_driver(
        profiles_dir=profiles_dir,
        headless=headless,
        user_agent=config.get("user_agent"),
        stealth=config.get("stealth_mode", True),
    )
    scraper = AmazonScraper(driver, config)

    try:
        if args.url or args.asin:
            target = args.url or args.asin
            data = scraper.scrape_product(target)
            if data:
                DataExporter.print_summary_card(data)
                DataExporter.save_to_csv([data], csv_path)
                DataExporter.save_to_json([data], json_path)
            else:
                print("[x] Failed to extract product data.")
                sys.exit(1)

        elif args.search:
            results = scraper.scrape_search_results(args.search, max_pages=args.pages)
            if results:
                print(f"[OK] Scraped {len(results)} items for query '{args.search}'.")
                DataExporter.save_to_csv(results, csv_path)
                DataExporter.save_to_json(results, json_path)
            else:
                print("[x] No search results found.")
                sys.exit(1)

        elif args.file:
            filepath = Path(args.file)
            if not filepath.exists():
                print(f"[!] File not found: {filepath}")
                sys.exit(1)
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            all_data = []
            for t in lines:
                item = scraper.scrape_product(t)
                if item:
                    DataExporter.print_summary_card(item)
                    all_data.append(item)
            if all_data:
                DataExporter.save_to_csv(all_data, csv_path)
                DataExporter.save_to_json(all_data, json_path)
                print(f"[OK] Batch scrape finished: {len(all_data)} items saved.")

    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Amazon Product & Price Scraper")
    parser.add_argument("--url", help="Scrape specific Amazon product URL")
    parser.add_argument("--asin", help="Scrape by 10-character Amazon ASIN")
    parser.add_argument("--search", help="Scrape search result listings by keyword")
    parser.add_argument("--pages", type=int, default=1, help="Number of search result pages to scrape")
    parser.add_argument("--file", help="Batch scrape URLs/ASINs from text file")
    parser.add_argument("--headless", action="store_true", default=None, help="Run Chrome in headless mode")
    parser.add_argument("--output-csv", help="Custom CSV output path")
    parser.add_argument("--output-json", help="Custom JSON output path")
    parser.add_argument("--web", action="store_true", help="Launch interactive Web Dashboard")
    parser.add_argument("--port", type=int, default=5050, help="Web Dashboard port (default: 5050)")

    args = parser.parse_args()
    config = load_config()

    if args.web:
        from web_server import run_server
        run_server(args.port)
    elif any([args.url, args.asin, args.search, args.file]):
        run_cli_args(args, config)
    else:
        print_banner()
        run_interactive(config)


if __name__ == "__main__":
    main()
