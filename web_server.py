#!/usr/bin/env python3
"""
Amazon Intelligence Scraper Web Server
Provides a modern REST API and web interface for live Amazon scraping,
smart budget query parsing, and in-stock filtering.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, send_from_directory

from amazon_scraper import AmazonScraper, DataExporter, parse_natural_query
try:
    from browser import get_driver
except Exception:
    get_driver = None

import tempfile

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "scraper_config.json"

if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = Path(tempfile.gettempdir()) / "scraped_data"
else:
    DATA_DIR = BASE_DIR / "scraped_data"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILE = DATA_DIR / "amazon_products.csv"
JSON_FILE = DATA_DIR / "amazon_products.json"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
logger = logging.getLogger("AmazonWebServer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Global Scraper State
current_job: Dict[str, Any] = {
    "status": "idle",  # "idle" | "running" | "completed" | "error"
    "message": "Scraper is ready.",
    "progress": 0,
    "current_page": 0,
    "total_pages": 1,
    "query": "",
    "parsed": {},
    "results": [],
    "logs": [],
    "stats": {
        "total_found": 0,
        "in_stock": 0,
        "lowest_price": None,
        "avg_price": None,
        "max_discount": None,
    },
    "error": None,
}
job_lock = threading.Lock()
stop_requested = False


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "domain": "https://www.amazon.in",
        "headless": True,
        "profiles_dir": "amazon_profiles",
        "output_dir": "scraped_data",
        "delay_range_seconds": [1.5, 3.0],
        "page_load_timeout": 30,
        "stealth_mode": True,
    }


def add_log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    with job_lock:
        current_job["logs"].append(entry)
        if len(current_job["logs"]) > 200:
            current_job["logs"] = current_job["logs"][-200:]
    logger.info(msg)


def run_scrape_worker(params: Dict[str, Any]) -> None:
    global current_job, stop_requested
    stop_requested = False

    query = params.get("query", "").strip()
    pages = int(params.get("pages", 1))
    in_stock_only = bool(params.get("in_stock_only", True))
    prime_only = bool(params.get("prime_only", False))
    min_rating = float(params["min_rating"]) if params.get("min_rating") else None
    min_price = float(params["min_price"]) if params.get("min_price") is not None and str(params["min_price"]).strip() != "" else None
    max_price = float(params["max_price"]) if params.get("max_price") is not None and str(params["max_price"]).strip() != "" else None
    headless = bool(params.get("headless", True))

    parsed = parse_natural_query(query)
    if min_price is None and parsed.get("min_price") is not None:
        min_price = parsed["min_price"]
    if max_price is None and parsed.get("max_price") is not None:
        max_price = parsed["max_price"]

    with job_lock:
        current_job["status"] = "running"
        current_job["message"] = f"Initializing stealth Chrome driver for '{query}'..."
        current_job["progress"] = 10
        current_job["query"] = query
        current_job["parsed"] = {
            "search_keyword": parsed.get("search_keyword", query),
            "target_brand": parsed.get("target_brand"),
            "target_model": parsed.get("target_model"),
            "min_price": min_price,
            "max_price": max_price,
            "detected_budget": parsed.get("detected_budget", ""),
            "in_stock_only": in_stock_only,
        }
        current_job["results"] = []
        current_job["logs"] = []
        current_job["error"] = None
        current_job["stats"] = {
            "total_found": 0,
            "in_stock": 0,
            "lowest_price": None,
            "avg_price": None,
            "max_discount": None,
        }

    add_log(f"Starting scrape for query: '{query}'")
    if parsed.get("target_brand"):
        add_log(f"Target Brand / Model Detected: '{parsed['target_brand']}' (Scraping all available models with verified sellers)")
    if parsed.get("detected_budget"):
        add_log(f"Smart Budget Detected: {parsed['detected_budget']}")
    add_log(f"Target Amazon Search Keyword: '{parsed.get('search_keyword')}' (Headless: {headless})")

    config = load_config()
    profiles_dir = BASE_DIR / config.get("profiles_dir", "amazon_profiles")

    driver = None
    try:
        scraper = AmazonScraper(driver=None, config=config)

        def progress_cb(ev: Dict[str, Any]) -> None:
            stage = ev.get("stage")
            if stage == "starting":
                with job_lock:
                    current_job["progress"] = 15
                    current_job["message"] = ev.get("message", "⚡ Turbo Engine scanning Amazon catalog...")
                add_log(ev.get("message", "⚡ Turbo Engine scanning Amazon catalog..."))
            elif stage == "page_loading":
                p = ev.get("current_page", 1)
                tot = ev.get("total_pages", pages)
                pct = int(25 + ((p - 1) / max(tot, 1)) * 55)
                with job_lock:
                    current_job["progress"] = pct
                    current_job["message"] = f"Scraping page {p}/{tot}..."
                add_log(f"Loading search page {p} of {tot}...")
            elif stage == "item_scraped":
                item = ev.get("item", {})
                with job_lock:
                    current_job["results"].append(item)
                    _update_stats_in_place(current_job)
                add_log(f"Scraped In-Stock item: {item.get('title', '')[:55]}... ({item.get('price', '')})")
            elif stage == "enriching_sellers":
                with job_lock:
                    current_job["progress"] = 88
                    current_job["message"] = ev.get("message", "Fetching verified sellers...")
                add_log(ev.get("message", "Fetching verified sellers..."))

        deep_scan = bool(params.get("deep_scan", True))
        add_log("⚡ Activating Ultra-Fast Turbo Engine (concurrent multi-angle scan)...")
        with job_lock:
            current_job["progress"] = 10
            current_job["message"] = "⚡ Turbo Engine active. Scanning Amazon..."

        results = scraper.scrape_search_results(
            query=query,
            max_pages=pages,
            min_price=min_price,
            max_price=max_price,
            in_stock_only=in_stock_only,
            prime_only=prime_only,
            min_rating=min_rating,
            progress_callback=progress_cb,
            deep_scan=deep_scan,
            use_turbo=True,
        )

        # Fallback to browser driver only if turbo returned 0 items
        if not results:
            add_log("Turbo engine returned 0 items, activating fallback browser engine...")
            with job_lock:
                current_job["progress"] = 25
                current_job["message"] = "Spawning anti-detection Chrome instance for fallback..."
            driver = get_driver(
                profiles_dir=profiles_dir,
                headless=headless,
                user_agent=config.get("user_agent"),
                stealth=config.get("stealth_mode", True),
            )
            scraper.driver = driver
            results = scraper.scrape_search_results(
                query=query,
                max_pages=pages,
                min_price=min_price,
                max_price=max_price,
                in_stock_only=in_stock_only,
                prime_only=prime_only,
                min_rating=min_rating,
                progress_callback=progress_cb,
                deep_scan=deep_scan,
                use_turbo=False,
            )

        # Save to database
        if results:
            add_log(f"Saving {len(results)} items to persistent CSV & JSON...")
            DataExporter.save_to_csv(results, CSV_FILE)
            DataExporter.save_to_json(results, JSON_FILE)

        with job_lock:
            current_job["status"] = "completed"
            current_job["progress"] = 100
            current_job["message"] = f"Finished! Found {len(results)} verified in-stock items."
            current_job["results"] = results
            _update_stats_in_place(current_job)

        add_log(f"Scrape completed successfully. {len(results)} items ready.")

    except Exception as e:
        logger.exception("Scraping worker error")
        with job_lock:
            current_job["status"] = "error"
            current_job["error"] = str(e)
            current_job["message"] = f"Scrape failed: {e}"
        add_log(f"ERROR: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _update_stats_in_place(job: Dict[str, Any]) -> None:
    items = job.get("results", [])
    if not items:
        return
    prices = [it["price_num"] for it in items if it.get("price_num") and it["price_num"] > 0]
    in_stock_count = sum(1 for it in items if it.get("in_stock", True))

    discounts = []
    for it in items:
        d = it.get("discount", "")
        if d and "%" in d:
            try:
                val = abs(int(d.replace("-", "").replace("%", "").strip()))
                discounts.append(val)
            except ValueError:
                pass

    brands = sorted(list(set(it.get("brand") for it in items if it.get("brand"))))
    job["brands"] = brands
    job["stats"] = {
        "total_found": len(items),
        "in_stock": in_stock_count,
        "lowest_price": min(prices) if prices else None,
        "avg_price": round(sum(prices) / len(prices)) if prices else None,
        "max_discount": f"{max(discounts)}%" if discounts else None,
        "brands_count": len(brands),
    }


@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


@app.route("/api/status", methods=["GET"])
@app.route("/status", methods=["GET"])
def get_status():
    with job_lock:
        return jsonify(current_job)


@app.route("/api/scrape", methods=["POST"])
@app.route("/scrape", methods=["POST"])
def start_scrape():
    global current_job
    data = request.get_json(silent=True, force=True) or {}
    if not data and request.data:
        try:
            data = json.loads(request.data.decode("utf-8", errors="ignore"))
        except Exception:
            pass
    if not data and request.form:
        data = request.form.to_dict()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"success": False, "error": "Search query cannot be empty."}), 400

    # In serverless environments (Vercel), background threads do not survive post-response.
    # Run synchronous Turbo Scrape directly and return results immediately!
    is_serverless = os.environ.get("VERCEL") is not None or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None
    if is_serverless:
        try:
            config = load_config()
            scraper = AmazonScraper(driver=None, config=config)
            # Cap pages to 1 on serverless to guarantee fast sub-5s response under Vercel timeout limit
            target_pages = min(max(int(data.get("pages", 1)), 1), 2)
            results = scraper.scrape_search_results(
                query=query,
                max_pages=target_pages,
                min_price=float(data["min_price"]) if data.get("min_price") is not None and str(data["min_price"]).strip() != "" else None,
                max_price=float(data["max_price"]) if data.get("max_price") is not None and str(data["max_price"]).strip() != "" else None,
                in_stock_only=bool(data.get("in_stock_only", True)),
                prime_only=bool(data.get("prime_only", False)),
                min_rating=float(data["min_rating"]) if data.get("min_rating") else None,
                deep_scan=bool(data.get("deep_scan", False)),
                use_turbo=True,
            )
            with job_lock:
                current_job["results"] = results
                current_job["status"] = "completed"
                current_job["progress"] = 100
                current_job["query"] = query
                _update_stats_in_place(current_job)
            return jsonify({
                "success": True,
                "status": "completed",
                "results": results,
                "stats": current_job.get("stats", {}),
                "message": f"Found {len(results)} verified in-stock items."
            })
        except Exception as e:
            logger.exception("Serverless scrape error")
            return jsonify({"success": False, "error": str(e)}), 500

    with job_lock:
        if current_job.get("status") == "running":
            return jsonify({"success": False, "error": "A scrape is already running."}), 409

    thread = threading.Thread(target=run_scrape_worker, args=(data,), daemon=True)
    thread.start()

    return jsonify({"success": True, "message": "Scrape task started in background."})


@app.route("/api/history", methods=["GET"])
@app.route("/history", methods=["GET"])
def get_history():
    """Retrieve saved items from CSV."""
    if not CSV_FILE.exists():
        return jsonify({"success": True, "items": []})

    items = []
    try:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_num = None
                try:
                    if row.get("price_num"):
                        p_num = float(row["price_num"])
                except ValueError:
                    pass
                row["price_num"] = p_num
                items.append(row)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # Return latest first
    items.reverse()
    return jsonify({"success": True, "count": len(items), "items": items[:100]})


@app.route("/api/parse-query", methods=["POST"])
@app.route("/parse-query", methods=["POST"])
def test_parse_query():
    data = request.get_json() or {}
    q = data.get("query", "")
    return jsonify(parse_natural_query(q))


def run_server(port: Optional[int] = None):
    port = port or int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"\n=======================================================")
    print(f"  AMAZON INTELLIGENCE SCRAPER - PRO WEB DASHBOARD")
    print(f"  Live at: http://{host}:{port}")
    print(f"=======================================================\n")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_server()
