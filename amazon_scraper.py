#!/usr/bin/env python3
"""
Amazon Product & Price Scraper Engine
Extracts product metadata, live pricing, stock, ratings, reviews, seller info, and search results.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    HAS_SELENIUM = True
except ImportError:
    webdriver = None
    HAS_SELENIUM = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AmazonScraper")

ASIN_PATTERN = re.compile(r"(?:/dp/|/gp/product/|/ASIN/|/product/)([A-Z0-9]{10})", re.IGNORECASE)
RAW_ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def extract_asin(input_str: str) -> Optional[str]:
    """Extract ASIN from a full URL or direct string."""
    input_str = input_str.strip()
    if RAW_ASIN_PATTERN.match(input_str):
        return input_str.upper()
    match = ASIN_PATTERN.search(input_str)
    if match:
        return match.group(1).upper()
    return None


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace and strip text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_price(price_str: Optional[str]) -> Optional[float]:
    """Convert price string like '₹24,999.00' or '$19.99' to float."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d.]", "", price_str.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


POPULAR_PHONE_BRANDS = [
    "AI+", "Apple", "Samsung", "OnePlus", "Xiaomi", "Redmi", "Realme", "iQOO", "Vivo",
    "Oppo", "Motorola", "Poco", "Nothing", "CMF", "Google", "Pixel", "Infinix", "Tecno",
    "Lava", "Itel", "Jio", "Micromax", "IKALL", "Karbonn", "Honor", "Nokia", "HMD", "Asus", "Sony"
]

BRAND_ALIASES = {
    "techno": "Tecno",
    "tecno": "Tecno",
    "ipone": "Apple",
    "ihpone": "Apple",
    "iphone": "Apple",
    "apple": "Apple",
    "samsng": "Samsung",
    "sumsung": "Samsung",
    "galaxy": "Samsung",
    "one plus": "OnePlus",
    "1plus": "OnePlus",
    "oneplus": "OnePlus",
    "readmi": "Redmi",
    "redme": "Redmi",
    "redmi": "Redmi",
    "xiaomi": "Xiaomi",
    "relme": "Realme",
    "real me": "Realme",
    "realme": "Realme",
    "narzo": "Realme",
    "noting": "Nothing",
    "nothing": "Nothing",
    "cmf": "CMF",
    "motrola": "Motorola",
    "moto": "Motorola",
    "motorola": "Motorola",
    "iqo": "iQOO",
    "iqoo": "iQOO",
    "infinx": "Infinix",
    "infinix": "Infinix",
    "poco": "Poco",
    "lava": "Lava",
    "itel": "Itel",
    "jio": "Jio",
    "jiobharat": "Jio",
    "nokia": "Nokia",
    "hmd": "HMD",
    "honor": "Honor",
    "nord": "OnePlus",
    "ai pulse": "AI+",
    "pulse 2": "AI+",
    "ai+": "AI+",
}

MODEL_PREFIX_BRANDS = {
    r"\b(?:s\d{2}|m\d{2}|a\d{2}|f\d{2}|z\s*fold|z\s*flip)\b": "Samsung",
    r"\bnord\b": "OnePlus",
    r"\bnarzo\b": "Realme",
    r"\bredmi\b": "Redmi",
    r"\bpoco\b": "Poco",
    r"\biphone\b": "Apple",
    r"\bpixel\b": "Google",
}

GENERIC_PHONE_KEYWORDS = {
    "phone", "phones", "mobile", "mobiles", "smartphone", "smartphones",
    "5g", "4g", "volte", "lte", "handset", "device", "best", "new", "latest",
    "in", "stock", "all", "buy", "online", "amazon", "price", "only", "verified",
}


def normalize_text_for_model(text: str) -> str:
    """Normalize text for model matching: replace + with plus, strip punctuation."""
    t = text.lower().replace("+", " plus ")
    t = re.sub(r"[\-_/(),:;]", " ", t)
    return " " + re.sub(r"\s+", " ", t).strip() + " "


def matches_exact_model(title: str, target_model: str) -> bool:
    """
    Strictly verifies that a product title corresponds to the exact target model requested,
    while permitting all variant configurations (different sellers, RAM/ROM sizes, colors).
    Rejects competing / adjacent sub-models (e.g. searching '12' rejects '12R'; searching '15'
    rejects '15 Pro' or '15 Plus'; searching 'X6' rejects 'X6 Neo' or 'X6 Pro').
    """
    if not title or not target_model:
        return True

    t = normalize_text_for_model(title)
    m_raw = normalize_text_for_model(target_model).strip()

    has_pro_max = bool(re.search(r"\bpro\s+max\b", m_raw))
    has_pro = bool(re.search(r"\bpro\b", m_raw)) and not has_pro_max
    has_max = bool(re.search(r"\bmax\b", m_raw)) and not has_pro_max
    has_ultra = bool(re.search(r"\bultra\b", m_raw))
    has_plus = bool(re.search(r"\bplus\b", m_raw))
    has_neo = bool(re.search(r"\bneo\b", m_raw))
    has_fe = bool(re.search(r"\bfe\b", m_raw))
    has_lite = bool(re.search(r"\blite\b", m_raw))
    has_ce = bool(re.search(r"\bce\b", m_raw))
    has_r = bool(re.search(r"\b\d+r\b", m_raw) or re.search(r"\br\b", m_raw))
    has_mini = bool(re.search(r"\bmini\b", m_raw))

    # All tokens of target model must be present as whole words
    m_tokens = m_raw.split()
    for tok in m_tokens:
        if not re.search(rf"\b{re.escape(tok)}\b", t):
            return False

    # Check for unwanted modifier / sub-model additions in product title
    if not has_pro_max and re.search(r"\bpro\s+max\b", t):
        return False
    if not (has_pro or has_pro_max) and re.search(r"\bpro\b", t):
        return False
    if not (has_max or has_pro_max) and re.search(r"\bmax\b", t):
        return False
    if not has_ultra and re.search(r"\bultra\b", t):
        return False
    if not has_plus and re.search(r"\bplus\b", t):
        return False
    if not has_neo and re.search(r"\bneo\b", t):
        return False
    if not has_fe and re.search(r"\bfe\b", t):
        return False
    if not has_lite and re.search(r"\blite\b", t):
        return False
    if not has_ce and re.search(r"\bce\b", t):
        return False
    if not has_mini and re.search(r"\bmini\b", t):
        return False

    # Check attached 'r', e.g. title has '12r' or '11r' when user searched '12' or '11'
    if not has_r:
        num_match = re.search(r"\b(\d+)\b", m_raw)
        if num_match:
            num = num_match.group(1)
            if re.search(rf"\b{num}r\b", t) or re.search(rf"\b{num}\s+r\b", t):
                return False

    return True

CURL_BIN = shutil.which("curl") or "curl"
COOKIE_FILE = Path(tempfile.gettempdir()) / "amazon_cookies.txt"


def ensure_amazon_cookies() -> None:
    """Ensure cookie jar exists and has fresh Amazon session cookies to avoid Akamai interstitial."""
    need_refresh = False
    if not COOKIE_FILE.exists() or COOKIE_FILE.stat().st_size < 50:
        need_refresh = True
    elif (time.time() - COOKIE_FILE.stat().st_mtime) > 1800:
        need_refresh = True

    if need_refresh:
        try:
            cmd = [
                CURL_BIN, "-s", "-c", str(COOKIE_FILE),
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "https://www.amazon.in/"
            ]
            subprocess.call(cmd, timeout=5)
        except Exception:
            pass


SELLER_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_seller_for_asin(asin: str) -> str:
    """
    Lightweight, ultra high-speed extractor for verified Amazon seller name and FBA status.
    Uses curl.exe with Chrome 130 headers and cookies to bypass bot challenges and extract buybox seller.
    """
    if not asin:
        return "Amazon Seller"
    ensure_amazon_cookies()
    url = f"https://www.amazon.in/dp/{asin}"
    cmd = [
        CURL_BIN, "-s", "--compressed",
        "-b", str(COOKIE_FILE), "-c", str(COOKIE_FILE),
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "-H", "Accept-Language: en-US,en;q=0.9",
        url
    ]
    try:
        html = subprocess.check_output(cmd, timeout=3).decode("utf-8", errors="ignore")
        if not html:
            return "Amazon Verified Seller"
        soup = BeautifulSoup(html, "html.parser")

        seller_name = ""
        # 1. Direct seller profile anchor
        s_el = (
            soup.find("a", id="sellerProfileTriggerId")
            or soup.select_one("a[href*='seller/at-a-glance']")
            or soup.select_one("a[href*='dp_merchant_link']")
        )
        if s_el:
            seller_name = clean_text(s_el.text)

        # 2. Tabular buybox container
        if not seller_name:
            tabular = soup.select_one("#tabular-buybox .tabular-buybox-text[tabular-attribute-name='Sold by']")
            if tabular:
                seller_name = clean_text(tabular.text)

        # 3. Merchant info div
        if not seller_name:
            merchant = soup.find("div", id="merchant-info")
            if merchant:
                m_txt = clean_text(merchant.text)
                sold_match = re.search(r"sold\s+by\s+([^.\n]+)", m_txt, re.IGNORECASE)
                if sold_match:
                    seller_name = sold_match.group(1).strip()
                elif m_txt:
                    seller_name = m_txt[:40]

        is_fba = bool(re.search(r"fulfilled\s+by\s+amazon|isamazonfulfilled=1", html, re.IGNORECASE))
        if seller_name:
            clean_s = re.sub(r"^(?:Sold by|Merchant:?)\s*", "", seller_name, flags=re.I).strip()
            if clean_s:
                return f"{clean_s} {'(FBA)' if is_fba else ''}".strip()
        if is_fba:
            return "Fulfilled by Amazon"
        return "Amazon Verified Seller"
    except Exception:
        return "Amazon Verified Seller"


MIN_PHONE_PRICE_BY_BRAND = {
    "Apple": 20000,
    "OnePlus": 12000,
    "iQOO": 8000,
    "Google": 18000,
    "Pixel": 18000,
    "Nothing": 14000,
    "CMF": 10000,
    "Samsung": 5500,
    "Xiaomi": 5500,
    "Redmi": 5000,
    "Realme": 5000,
    "Poco": 5000,
    "Motorola": 5500,
    "Vivo": 5500,
    "Oppo": 5500,
    "Honor": 8000,
    "Tecno": 5000,
    "Infinix": 5000,
    "AI+": 3500,
    "Lava": 800,
    "Itel": 800,
    "Nokia": 800,
    "HMD": 800,
    "Jio": 800,
    "Micromax": 800,
    "IKALL": 800,
}

NON_PHONE_PATTERNS = [
    # Watches & Wearables ("ghadi") - ABSOLUTE REJECT
    r"\b(?:watch|smartwatch|smart watch|wrist watch|analog watch|digital watch|watch for|smart band|fitness band|activity tracker)\b",
    
    # Phone Cases, Covers, Holsters & Panels - ABSOLUTE REJECT
    r"\b(?:cover|covers|case|cases|flip cover|back cover|flip case|back case|protective case|shockproof case|bumper case|leather case|silicone case|clear case|carbon case|phone cover|phone case|back panel|panel replacement|housing body|pouch|holster|sleeve bag)\b",
    
    # Glass & Screen Protectors - ABSOLUTE REJECT
    r"\b(?:tempered glass|screen protector|camera lens protector|privacy glass|guard for|display glass|front glass replacement)\b",
    r"\b(?:compatible with|cover compatible|case compatible)\b",
    
    # Replacement Parts & Batteries - ABSOLUTE REJECT
    r"\b(?:replacement|spare parts?|replacement battery|mobile battery|li-ion battery|internal battery|battery for|combo folder|display replacement|lcd screen replacement|touch screen digitizer|sim tray|flex cable)\b",
    
    # Cables & Chargers - ABSOLUTE REJECT
    r"\b(?:charging cable|charger cable|usb cable|type-c cable|lightning cable|adapter|charger adapter|power adapter|wall charger|car charger|wireless charger|docking station|power bank|powerbank)\b",
    
    # Audio Accessories - ABSOLUTE REJECT
    r"\b(?:bluetooth speaker|speaker|soundbar|tws|earbuds|earphones|headphone|headphones|neckband|microphone|mic)\b",
    
    # Mounts, Stands & Skins
    r"\b(?:phone holder|mobile holder|car mount|bike mount|mobile stand|tripod|gimbal|selfie stick|ring light|ring holder|pop socket|skin wrap|wrap skin|decal sticker)\b",
    
    # Musical Instruments
    r"\b(?:guitar|acoustic|semi-acoustic|cutaway|basswood|rosewood|ukulele|violin|piano|harmonium|synthesizer|flute|drum|amplifier)\b",
    
    # Appliances & TVs
    r"\b(?:television|smart tv|led tv|oled tv|refrigerator|fridge|washing machine|microwave|oven|air conditioner|cooler|fan|vacuum cleaner|water purifier|geyser)\b",
    
    # Laptops & PC Parts
    r"\b(?:laptop|notebook|chromebook|macbook|desktop pc|monitor|motherboard|graphic card|graphics card|gpu|cpu processor|printer|scanner|mechanical keyboard)\b",
]

NON_PHONE_REGEX = re.compile("|".join(NON_PHONE_PATTERNS), re.IGNORECASE)

POSITIVE_PHONE_PATTERNS = [
    r"\b(?:smartphone|smartphones|mobile phone|mobile phones|basic mobile|feature phone|cellphone|handset|keypad phone|keypad mobile|keypad)\b",
    r"\b(?:5g|4g volte|4g lte|dual sim)\b",
    r"\b\d+\s*(?:gb|mb)\s*(?:ram|rom|storage)\b",
    r"\b(?:snapdragon|dimensity|bionic|helio|unisoc|exynos|tensor)\b",
]
POSITIVE_PHONE_REGEX = re.compile("|".join(POSITIVE_PHONE_PATTERNS), re.IGNORECASE)


def is_valid_phone_handset(title: str, price_num: Optional[float] = None, target_brand: Optional[str] = None) -> bool:
    """Strictly validates whether a product listing is an authentic mobile phone handset."""
    if not title:
        return False
    t = title.lower().strip()
    
    # 1. Reject if matches any non-phone category (watches, covers, cases, panels, batteries, cables, etc.)
    if NON_PHONE_REGEX.search(t):
        return False
        
    # 2. Reject if price is below brand-specific handset minimum threshold
    if target_brand:
        min_allowed = MIN_PHONE_PRICE_BY_BRAND.get(target_brand, 800)
        if price_num is not None and price_num < min_allowed:
            return False
    elif price_num is not None and price_num < 800:
        return False
        
    # 3. Must match positive phone handset indicators (unless brand is known phone brand with specs)
    if POSITIVE_PHONE_REGEX.search(t):
        return True
        
    for b in POPULAR_PHONE_BRANDS:
        if re.search(rf"\b{re.escape(b.lower())}\b", t):
            if re.search(r"\b(?:\d+\s*gb|\d+\s*inch|android|camera|display|titanium)\b", t):
                return True
                
    return False


def is_phone_accessory(title: str, price_num: Optional[float] = None, target_brand: Optional[str] = None) -> bool:
    """Detect if listing is an accessory or non-phone."""
    return not is_valid_phone_handset(title, price_num, target_brand)


def extract_brand_and_specs(title: str) -> Dict[str, Any]:
    """Extract known brand and key tech specifications (5G, RAM, Storage, etc.) from title."""
    if not title:
        return {"brand": "", "specs": []}

    brand = ""
    title_lower = title.lower()

    if "ai+" in title_lower or "ai pulse" in title_lower or "ai nova" in title_lower or "pulse 2" in title_lower:
        brand = "AI+"
    elif "iphone" in title_lower or "apple" in title_lower:
        brand = "Apple"
    else:
        for alias, canon in BRAND_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", title_lower):
                brand = canon
                break
        if not brand:
            for b in POPULAR_PHONE_BRANDS:
                if re.search(rf"\b{re.escape(b.lower())}\b", title_lower):
                    brand = b
                    break

    if not brand and title:
        first_token = title.split()[0]
        if len(first_token) >= 2 and first_token.isalnum():
            brand = first_token.capitalize()

    specs: List[str] = []
    if re.search(r"\b5G\b", title, re.IGNORECASE):
        specs.append("5G")

    ram_match = re.search(r"(\d+\s*GB\s*RAM)", title, re.IGNORECASE)
    if ram_match:
        specs.append(clean_text(ram_match.group(1)).upper())

    rom_match = re.search(r"(\d+\s*GB(?:\s*(?:Storage|ROM))?)", title, re.IGNORECASE)
    if rom_match:
        val = clean_text(rom_match.group(1)).upper()
        if not any(val in s for s in specs):
            specs.append(val)

    disp_match = re.search(r"\b(AMOLED|OLED|FHD\+?|120\s*Hz|90\s*Hz)\b", title, re.IGNORECASE)
    if disp_match:
        specs.append(disp_match.group(1).upper())

    return {
        "brand": brand,
        "specs": specs[:4],
    }


def parse_natural_query(query: str) -> Dict[str, Any]:
    """
    Intelligently parses natural queries:
      - Brand/Model Search (e.g. 'AI+ Pulse 2', 'Samsung', 'OnePlus Nord', 'iPhone 15')
        -> Sets target_brand & target_model, leaves price unconstrained if no budget specified.
      - Budget Search (e.g. 'phones under 25k', 'laptops below 50000')
        -> Sets max_price, detected_budget, and generic keywords.
    """
    raw = query.strip()
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    detected_budget = ""

    between_match = re.search(
        r"(?:between|from)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh)?\s*(?:to|and|-)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh)?",
        raw,
        re.IGNORECASE,
    )
    if between_match:
        def _to_num(val_str: str, unit: Optional[str]) -> float:
            v = float(val_str)
            if unit:
                u = unit.lower()
                if u in ("k", "thousand") or (v <= 100 and v > 0):
                    v *= 1000
                elif u in ("l", "lac", "lakh"):
                    v *= 100000
            elif v <= 100 and v > 0:
                v *= 1000
            return v

        min_price = _to_num(between_match.group(1), between_match.group(2))
        max_price = _to_num(between_match.group(3), between_match.group(4))
        detected_budget = f"₹{int(min_price):,} - ₹{int(max_price):,}"
        cleaned = raw[:between_match.start()] + " " + raw[between_match.end():]
    else:
        under_match = re.search(
            r"(?:under|below|less\s+than|up\s+to|within|max|<|<=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh)?",
            raw,
            re.IGNORECASE,
        )
        if under_match:
            val = float(under_match.group(1))
            unit = (under_match.group(2) or "").lower()
            if unit in ("k", "thousand") or (val <= 100 and val > 0):
                val *= 1000
            elif unit in ("l", "lac", "lakh"):
                val *= 100000
            max_price = val
            detected_budget = f"Under ₹{int(max_price):,}"
            cleaned = raw[:under_match.start()] + " " + raw[under_match.end():]
        else:
            above_match = re.search(
                r"(?:above|over|more\s+than|min|>|>=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh)?",
                raw,
                re.IGNORECASE,
            )
            if above_match:
                val = float(above_match.group(1))
                unit = (above_match.group(2) or "").lower()
                if unit in ("k", "thousand") or (val <= 100 and val > 0):
                    val *= 1000
                elif unit in ("l", "lac", "lakh"):
                    val *= 100000
                min_price = val
                detected_budget = f"Above ₹{int(min_price):,}"
                cleaned = raw[:above_match.start()] + " " + raw[above_match.end():]
            else:
                cleaned = raw

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = raw

    # Brand and Model detection
    target_brand = None
    target_model = None
    cleaned_lower = cleaned.lower()

    # 1. Detect Brand
    if "pulse" in cleaned_lower or "ai+" in cleaned_lower or "ai pulse" in cleaned_lower or "ai plus" in cleaned_lower or "nova 5g" in cleaned_lower:
        target_brand = "AI+"
    elif "iphone" in cleaned_lower or "apple" in cleaned_lower:
        target_brand = "Apple"
    elif "galaxy" in cleaned_lower:
        target_brand = "Samsung"
    else:
        for alias, canon in BRAND_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", cleaned_lower):
                target_brand = canon
                break
        if not target_brand:
            for b in POPULAR_PHONE_BRANDS:
                if re.search(rf"\b{re.escape(b.lower())}\b", cleaned_lower):
                    target_brand = b
                    break
        if not target_brand:
            for pat, b in MODEL_PREFIX_BRANDS.items():
                if re.search(pat, cleaned_lower):
                    target_brand = b
                    break

    # 2. Extract specific model name/tokens if user searched a specific model
    cleaned_for_model = re.sub(r"\b\d+\s*(?:gb|tb|mb)(?:\s*(?:ram|rom|storage))?\b", " ", cleaned, flags=re.I)
    if target_brand:
        brand_tokens = [target_brand.lower()]
        for alias, canon in BRAND_ALIASES.items():
            if canon.lower() == target_brand.lower():
                brand_tokens.append(alias.lower())
        for bt in brand_tokens:
            cleaned_for_model = re.sub(rf"\b{re.escape(bt)}\b", " ", cleaned_for_model, flags=re.I)

    words = cleaned_for_model.split()
    model_words = [w for w in words if w.lower() not in GENERIC_PHONE_KEYWORDS]
    if model_words:
        target_model = " ".join(model_words).strip(" -_/")
    else:
        target_model = None

    # Optimize search keyword for Amazon query
    if target_brand and target_model:
        if target_brand == "Apple" and ("iphone" not in target_model.lower()):
            search_keyword = f"iPhone {target_model}"
        else:
            search_keyword = f"{target_brand} {target_model}"
    elif target_brand:
        # If user typed just the brand name (e.g. "Samsung" or "OnePlus"), append "smartphones"
        search_keyword = f"{target_brand} smartphones"
    else:
        if cleaned_lower in ("phones", "phone", "mobile", "mobiles"):
            search_keyword = "smartphones"
        elif "phone" in cleaned_lower and "smart" not in cleaned_lower:
            search_keyword = cleaned_lower.replace("phone", "smartphone")
        else:
            search_keyword = cleaned

    return {
        "raw_query": raw,
        "search_keyword": search_keyword,
        "target_brand": target_brand,
        "target_model": target_model,
        "min_price": min_price,
        "max_price": max_price,
        "detected_budget": detected_budget,
    }


class AmazonScraper:
    def __init__(self, driver: Optional[webdriver.Chrome] = None, config: Optional[Dict[str, Any]] = None):
        self.driver = driver
        self.config = config or {}
        self.domain = self.config.get("domain", "https://www.amazon.in").rstrip("/")
        self.delay_min = self.config.get("delay_range_seconds", [2.0, 4.0])[0]
        self.delay_max = self.config.get("delay_range_seconds", [2.0, 4.0])[1]
        self.timeout = self.config.get("page_load_timeout", 30)

    def random_sleep(self) -> None:
        """Introduce polite random delay between requests."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    def check_and_handle_captcha(self) -> bool:
        """Detect Amazon robot-check / CAPTCHA page and alert user."""
        current_source = self.driver.page_source.lower()
        if (
            "enter the characters you see below" in current_source
            or "type the characters you see in this image" in current_source
            or "robot check" in current_source
        ):
            logger.warning("[!] Amazon CAPTCHA detected!")
            print("\n" + "=" * 60)
            print(">>> [ACTION NEEDED] Amazon Robot Check / CAPTCHA triggered!")
            print(">>> Please solve the CAPTCHA in the opened Chrome window.")
            print("=" * 60 + "\n")

            # Wait up to 120 seconds for user to solve
            max_wait = 120
            start = time.time()
            while time.time() - start < max_wait:
                time.sleep(3)
                source_after = self.driver.page_source.lower()
                if "enter the characters you see below" not in source_after and "robot check" not in source_after:
                    logger.info("[OK] CAPTCHA resolved successfully!")
                    return True

            logger.error("[x] CAPTCHA wait timed out after 120s.")
            return False
        return True

    def build_product_url(self, asin_or_url: str) -> str:
        """Ensure valid Amazon product URL from ASIN or URL."""
        asin = extract_asin(asin_or_url)
        if asin and not asin_or_url.startswith("http"):
            return f"{self.domain}/dp/{asin}"
        return asin_or_url

    def scrape_product(self, asin_or_url: str) -> Optional[Dict[str, Any]]:
        """Scrape full product details from a product page."""
        url = self.build_product_url(asin_or_url)
        asin = extract_asin(url) or ""

        logger.info(f"Navigating to product: {url}")
        try:
            self.driver.get(url)
        except TimeoutException:
            logger.warning("Page load timed out, attempting to parse available content...")
        except WebDriverException as e:
            logger.error(f"Failed to load URL {url}: {e}")
            return None

        logger.info(f"Page loaded. Title: '{self.driver.title}' | URL: {self.driver.current_url}")

        if not self.check_and_handle_captcha():
            return None

        self.random_sleep()

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        return self._extract_product_details(soup, url, asin)

    def _extract_product_details(
        self, soup: BeautifulSoup, url: str, asin: str
    ) -> Dict[str, Any]:
        """Extract structured data fields from parsed BeautifulSoup DOM."""
        # 1. Title
        title_el = (
            soup.find("span", id="productTitle")
            or soup.find("h1", id="title")
            or soup.select_one("h1.a-size-large")
        )
        title = clean_text(title_el.text) if title_el else ""

        # 2. ASIN
        if not asin:
            asin_el = soup.find("input", id="ASIN")
            if asin_el and asin_el.get("value"):
                asin = asin_el["value"].strip()

        # 3. Current Price
        price_text = ""
        price_selectors = [
            ".a-price.aok-align-center .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".priceToPay .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#price",
            ".a-price .a-offscreen",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el and el.text:
                candidate = clean_text(el.text)
                if any(c.isdigit() for c in candidate):
                    price_text = candidate
                    break

        price_num = parse_price(price_text)

        # 4. MRP / Original Price
        mrp_text = ""
        mrp_selectors = [
            ".a-price.a-text-price .a-offscreen",
            ".basisPrice .a-offscreen",
            "#listPrice",
            "span.a-price.a-text-price[data-a-strike='true'] .a-offscreen",
        ]
        for sel in mrp_selectors:
            el = soup.select_one(sel)
            if el and el.text:
                candidate = clean_text(el.text)
                if any(c.isdigit() for c in candidate):
                    mrp_text = candidate
                    break

        mrp_num = parse_price(mrp_text)

        # 5. Discount Percentage
        discount = ""
        discount_el = (
            soup.select_one(".savingsPercentage")
            or soup.select_one(".reinventPriceSavingsPercentageMargin")
            or soup.select_one("#dealprice_savings .priceBlockSavingsString")
        )
        if discount_el:
            discount = clean_text(discount_el.text)
        elif price_num and mrp_num and mrp_num > price_num:
            pct = round(((mrp_num - price_num) / mrp_num) * 100)
            discount = f"-{pct}%"

        # 6. Availability / Stock
        availability = "Unknown"
        avail_el = soup.find("div", id="availability")
        if avail_el:
            availability = clean_text(avail_el.text)
        else:
            out_of_stock_el = soup.find("div", id="outOfStock")
            if out_of_stock_el:
                availability = "Currently unavailable."

        in_stock = True
        avail_lower = availability.lower()
        if "currently unavailable" in avail_lower or "out of stock" in avail_lower:
            in_stock = False

        # 7. Rating and Review Count
        rating_score = ""
        rating_el = (
            soup.select_one("#acrPopover span.a-icon-alt")
            or soup.select_one(".a-icon-star-small .a-icon-alt")
            or soup.select_one("span[data-hook='rating-out-of-text']")
        )
        if rating_el:
            rating_score = clean_text(rating_el.text)

        review_count = ""
        review_el = soup.find("span", id="acrCustomerReviewText") or soup.select_one(
            "span[data-hook='total-review-count']"
        )
        if review_el:
            review_count = clean_text(review_el.text)

        # 8. Brand
        brand = ""
        brand_el = (
            soup.find("a", id="bylineInfo")
            or soup.select_one("tr.po-brand td.po-break-word")
            or soup.select_one(".po-brand .a-span9")
        )
        if brand_el:
            brand = clean_text(brand_el.text).replace("Brand:", "").replace("Visit the", "").replace("Store", "").strip()

        # 9. Seller ("Sold by" & "Fulfilled by")
        seller = ""
        merchant_info = soup.find("div", id="merchant-info")
        if merchant_info:
            seller = clean_text(merchant_info.text)
        else:
            sold_by_el = soup.select_one("#tabular-buybox .tabular-buybox-text[tabular-attribute-name='Sold by'] a")
            if sold_by_el:
                seller = clean_text(sold_by_el.text)

        # 10. Prime Eligibility
        is_prime = bool(soup.select_one(".a-icon-prime") or soup.find("i", class_="a-icon-prime"))

        # 11. Delivery Info
        delivery_info = ""
        deliv_el = soup.find("div", id="mir-layout-DELIVERY_BLOCK") or soup.find("div", id="deliveryBlockMessage")
        if deliv_el:
            delivery_info = clean_text(deliv_el.text)

        # 12. Key Features / Bullets
        bullets = []
        feature_div = soup.find("div", id="feature-bullets")
        if feature_div:
            for li in feature_div.select("ul li span.a-list-item"):
                txt = clean_text(li.text)
                if txt and not txt.startswith("›"):
                    bullets.append(txt)

        # 13. Main High-Res Image
        image_url = ""
        img_el = soup.find("img", id="landingImage") or soup.find("img", id="imgBlkFront")
        if img_el:
            image_url = (
                img_el.get("data-old-hires")
                or img_el.get("data-a-dynamic-image")
                or img_el.get("src")
                or ""
            )
            # data-a-dynamic-image is a JSON dict of URLs to dimensions
            if image_url.startswith("{"):
                try:
                    img_dict = json.loads(image_url)
                    if img_dict:
                        image_url = list(img_dict.keys())[0]
                except Exception:
                    image_url = img_el.get("src", "")

        return {
            "asin": asin,
            "title": title,
            "price": price_text,
            "price_num": price_num,
            "mrp": mrp_text,
            "mrp_num": mrp_num,
            "discount": discount,
            "in_stock": in_stock,
            "availability": availability,
            "rating": rating_score,
            "review_count": review_count,
            "brand": brand,
            "seller": seller,
            "is_prime": is_prime,
            "delivery": delivery_info,
            "image_url": image_url,
            "features": " | ".join(bullets),
            "url": url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _parse_search_item_node(
        self,
        item: BeautifulSoup,
        query: str,
        target_brand: Optional[str] = None,
        target_model: Optional[str] = None,
        is_phone_query: bool = True,
        in_stock_only: bool = True,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        prime_only: bool = False,
        min_rating: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        asin = item.get("data-asin", "").strip()
        if not asin:
            return None

        # Title & URL
        recipe = item.find("div", {"data-cy": "title-recipe"})
        title = ""
        full_url = ""

        if recipe:
            link_el = recipe.find("a", href=lambda h: h and ("/dp/" in h or "/gp/" in h)) or recipe.find("a")
            if link_el:
                href = link_el.get("href", "")
                full_url = urljoin(self.domain, href)

            brand_sub = recipe.find("h2", class_=lambda c: c and "a-size-mini" in c) or recipe.select_one(".a-row.a-color-secondary span")
            brand_header = clean_text(brand_sub.text) if brand_sub else ""

            main_h2 = recipe.find("h2", class_=lambda c: c and "a-size-medium" in c) or recipe.find("h2", class_=lambda c: c and "a-color-base" in c) or recipe.find("h2")
            if main_h2:
                title = main_h2.get("aria-label") or clean_text(main_h2.text)
            if not title and link_el:
                title = link_el.get("aria-label") or clean_text(link_el.text)

            if brand_header and brand_header.lower() not in title.lower():
                title = f"{brand_header} {title}".strip()

        if not title:
            title_selectors = [
                "div[data-cy='title-recipe'] h2 span",
                "h2.a-color-base span",
                "h2 a span",
                "h2.a-size-medium.a-text-normal span",
                "h2.a-text-normal",
                "a.a-link-normal.s-link-style span",
                "a.a-text-normal span",
            ]
            for t_sel in title_selectors:
                t_el = item.select_one(t_sel)
                if t_el and t_el.text:
                    candidate = clean_text(t_el.text)
                    if len(candidate) > 2:
                        title = candidate
                        break

        # Fallback check for brand header across whole card if not found in recipe
        if not brand_header:
            b_el = (
                item.select_one("h2.a-size-mini span.a-color-base")
                or item.find("h2", class_=lambda c: c and "a-size-mini" in c)
                or item.select_one(".a-row.a-color-secondary span")
            )
            if b_el:
                brand_header = clean_text(b_el.text)

        if brand_header and brand_header.lower() not in title.lower():
            title = f"{brand_header} {title}".strip()
        elif target_brand and target_brand.lower() not in title.lower():
            competing = [b for b in POPULAR_PHONE_BRANDS if b.lower() != target_brand.lower() and re.search(rf"\b{re.escape(b.lower())}\b", title.lower())]
            if not competing:
                title = f"{target_brand} {title}".strip()

        if not full_url:
            link_el = item.select_one("a[href*='/dp/']") or item.select_one("h2 a")
            href = link_el["href"] if link_el and link_el.has_attr("href") else f"/dp/{asin}"
            full_url = urljoin(self.domain, href)

        # Price & MRP
        price_text = ""
        price_el = item.select_one(".a-price .a-offscreen")
        if price_el:
            price_text = clean_text(price_el.text)
        price_num = parse_price(price_text)

        mrp_text = ""
        mrp_el = item.select_one(".a-price.a-text-price .a-offscreen")
        if mrp_el:
            mrp_text = clean_text(mrp_el.text)
        mrp_num = parse_price(mrp_text)

        # Accessory check
        if is_phone_query and is_phone_accessory(title, price_num, target_brand):
            return None

        # Brand validation
        brand_and_specs = extract_brand_and_specs(title)
        brand = brand_and_specs["brand"]
        specs = brand_and_specs["specs"]

        if target_brand:
            title_l = title.lower()
            brand_match = False
            if target_brand == "AI+":
                if "ai+" in title_l or "ai pulse" in title_l or "pulse 2" in title_l or "ai nova" in title_l or brand == "AI+":
                    brand_match = True
            elif target_brand == "Apple":
                if "iphone" in title_l or "apple" in title_l or brand == "Apple":
                    brand_match = True
            else:
                if target_brand.lower() in title_l or (brand and brand.lower() == target_brand.lower()):
                    brand_match = True

            if not brand_match:
                return None

            if target_model:
                if not matches_exact_model(title, target_model):
                    return None

        # Stock check
        card_text = item.get_text().lower()
        is_out_of_stock = (
            "currently unavailable" in card_text
            or "out of stock" in card_text
            or "temporarily out of stock" in card_text
        )
        if price_num is None or price_num <= 0:
            is_out_of_stock = True

        in_stock = not is_out_of_stock
        availability = "In stock" if in_stock else "Out of stock"

        if in_stock_only and not in_stock:
            return None

        # Price bounds
        if max_price is not None and price_num is not None and price_num > max_price:
            return None
        if min_price is not None and price_num is not None and price_num < min_price:
            return None

        is_prime = bool(item.select_one(".a-icon-prime"))
        if prime_only and not is_prime:
            return None

        rating = ""
        rating_num = None
        rating_el = item.select_one("i.a-icon-star-small span.a-icon-alt") or item.select_one("span.a-icon-alt")
        if rating_el:
            rating = clean_text(rating_el.text)
            r_match = re.search(r"(\d+(?:\.\d+)?)", rating)
            if r_match:
                try:
                    rating_num = float(r_match.group(1))
                except ValueError:
                    pass

        if min_rating is not None and rating_num is not None and rating_num < min_rating:
            return None

        review_count = ""
        reviews_el = item.select_one("span.a-size-base.s-underline-text") or item.select_one("span.s-underline-text")
        if reviews_el:
            review_count = clean_text(reviews_el.text)

        img_el = item.select_one("img.s-image")
        img_url = img_el["src"] if img_el and img_el.has_attr("src") else ""

        discount = ""
        if price_num and mrp_num and mrp_num > price_num:
            pct = round(((mrp_num - price_num) / mrp_num) * 100)
            discount = f"-{pct}%"

        badge = ""
        badge_el = item.select_one(".a-badge-text") or item.select_one(".s-ribbon-text")
        if badge_el:
            badge = clean_text(badge_el.text)

        return {
            "asin": asin,
            "title": title,
            "price": price_text or (f"₹{price_num:,.2f}" if price_num else "N/A"),
            "price_num": price_num,
            "mrp": mrp_text,
            "mrp_num": mrp_num,
            "discount": discount,
            "in_stock": in_stock,
            "availability": availability,
            "rating": rating,
            "rating_num": rating_num,
            "review_count": review_count,
            "brand": brand or target_brand or "Amazon",
            "seller": "Fulfilled by Amazon" if is_prime else "Amazon Verified",
            "is_prime": is_prime,
            "delivery": "Prime Delivery" if is_prime else "",
            "image_url": img_url,
            "specs": specs,
            "badge": badge,
            "features": ", ".join(specs),
            "search_query": query,
            "url": full_url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def scrape_search_results_turbo(
        self,
        query: str,
        max_pages: int = 2,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        in_stock_only: bool = True,
        prime_only: bool = False,
        min_rating: Optional[float] = None,
        progress_callback: Optional[Any] = None,
        deep_scan: bool = True,
    ) -> List[Dict[str, Any]]:
        """High-speed concurrent HTTP engine fetching all catalog pages in seconds."""
        parsed = parse_natural_query(query)
        actual_keyword = parsed["search_keyword"] or query
        target_brand = parsed.get("target_brand")
        target_model = parsed.get("target_model")

        if min_price is None and parsed.get("min_price") is not None:
            min_price = parsed["min_price"]
        if max_price is None and parsed.get("max_price") is not None:
            max_price = parsed["max_price"]

        is_laptop_query = any(k in query.lower() for k in ("laptop", "notebook", "chromebook", "macbook"))
        is_phone_query = not is_laptop_query and (
            target_brand is not None
            or any(k in query.lower() for k in ("phone", "phones", "mobile", "mobiles", "smartphone", "smartphones", "pulse", "handset", "5g", "keypad"))
        )

        scan_urls = []
        brand_sweep_terms = {
            "apple": ("apple", "iphone", "apple iphone", "apple iphones", "iphones", "apple phone", "apple phones", "apple mobile", "apple smartphones"),
            "poco": ("poco", "poco phone", "poco phones", "poco mobile", "poco smartphones", "poco 5g"),
            "samsung": ("samsung", "samsung galaxy", "samsung phone", "samsung phones", "samsung mobile", "samsung smartphones"),
            "oneplus": ("oneplus", "oneplus nord", "oneplus phone", "oneplus phones", "oneplus mobile", "oneplus smartphones"),
            "redmi": ("redmi", "redmi note", "redmi phone", "redmi phones", "redmi mobile", "redmi smartphones", "xiaomi"),
            "realme": ("realme", "realme narzo", "realme phone", "realme phones", "realme mobile", "realme smartphones"),
            "motorola": ("moto", "motorola", "motorola phone", "motorola phones", "motorola mobile", "motorola smartphones"),
            "iqoo": ("iqoo", "iqoo phone", "iqoo phones", "iqoo mobile", "iqoo smartphones"),
            "tecno": ("tecno", "techno", "tecno phone", "tecno phones", "tecno mobile", "tecno smartphones", "tecno spark", "tecno pova", "tecno camon", "tecno pop"),
            "infinix": ("infinix", "infinix phone", "infinix phones", "infinix mobile", "infinix smartphones", "infinix gt", "infinix note", "infinix zero", "infinix smart"),
            "itel": ("itel", "itel phone", "itel phones", "itel mobile", "itel smartphones"),
            "lava": ("lava", "lava phone", "lava phones", "lava mobile", "lava smartphones", "lava agni", "lava blaze", "lava yuva"),
            "nothing": ("nothing", "nothing phone", "nothing phones", "cmf", "cmf phone"),
            "vivo": ("vivo", "vivo phone", "vivo phones", "vivo mobile", "vivo smartphones", "vivo v", "vivo t", "vivo y"),
            "oppo": ("oppo", "oppo phone", "oppo phones", "oppo mobile", "oppo smartphones", "oppo reno", "oppo f"),
            "google": ("google", "pixel", "google pixel", "google phone", "google phones"),
            "nokia": ("nokia", "hmd", "nokia phone", "nokia phones", "nokia mobile", "nokia 105", "nokia g42"),
        }
        b_key = target_brand.lower() if target_brand else ""
        valid_sweep_queries = brand_sweep_terms.get(b_key, (
            b_key,
            f"{b_key} phone",
            f"{b_key} phones",
            f"{b_key} mobile",
            f"{b_key} smartphones"
        )) if b_key else ()

        is_generic_brand_search = bool(
            b_key and (
                query.strip().lower() in valid_sweep_queries
                or (target_model is None and query.strip().lower().replace("+", " ") in valid_sweep_queries)
            )
        )

        if is_generic_brand_search and target_brand == "Apple":
            # Deep Apple iPhone catalog scan across 10 pages + all model generations in Smartphones category node 1389401031
            for p in range(1, 11):
                scan_urls.append(f"{self.domain}/s?k=apple+iphone&rh=n%3A1389401031&page={p}")
                scan_urls.append(f"{self.domain}/s?k=iphone&rh=n%3A1389401031&page={p}")
            for s in ["iphone+16", "iphone+15", "iphone+14", "iphone+13", "iphone+16+pro", "iphone+15+pro", "iphone+plus", "iphone+se", "iphone+12", "iphone+11"]:
                for p in range(1, 3):
                    scan_urls.append(f"{self.domain}/s?k={s}&rh=n%3A1389401031&page={p}")
        elif is_generic_brand_search and target_brand == "Poco":
            # Full brand catalog scan across all 15 pages in Smartphones category node 1389401031
            for p in range(1, 16):
                scan_urls.append(f"{self.domain}/s?k=poco&rh=n%3A1389401031&page={p}")
            # Also add specific series queries under category node to capture all unindexed models
            for s in ["poco+5g", "poco+m6", "poco+x6", "poco+c65", "poco+f6", "poco+c61", "poco+m5", "poco+m4", "poco+x5", "poco+c55"]:
                for p in range(1, 3):
                    scan_urls.append(f"{self.domain}/s?k={s}&rh=n%3A1389401031&page={p}")
        elif is_generic_brand_search and target_brand == "AI+":
            for a in ["ai pulse 2", "ai+ pulse 2", "ai+ nova 5g", "ai+ smartphones"]:
                for p in range(1, max(max_pages, 3) + 1):
                    scan_urls.append(f"{self.domain}/s?k={a.replace(' ', '+')}&rh=n%3A1389401031&page={p}")
        elif is_generic_brand_search:
            for p in range(1, max(max_pages, 12) + 1):
                scan_urls.append(f"{self.domain}/s?k={target_brand.lower()}&rh=n%3A1389401031&page={p}")
            for a in [f"{target_brand.lower()}+5g", f"{target_brand.lower()}+smartphones"]:
                for p in range(1, 3):
                    scan_urls.append(f"{self.domain}/s?k={a}&rh=n%3A1389401031&page={p}")
        else:
            # Particular phone or model search (e.g. "Poco M6", "iPhone 15", "Samsung S24", "phones under 25k")
            angles = [actual_keyword]
            if deep_scan and is_phone_query and not any(k in actual_keyword.lower() for k in ("phone", "mobile", "smartphone")):
                angles.append(f"{actual_keyword} 5g mobile")
            target_depth = max(max_pages, 5) if target_model else max(max_pages, 3)
            for a in angles:
                for p in range(1, target_depth + 1):
                    params = [f"k={a.replace(' ', '+')}", f"page={p}"]
                    if is_phone_query:
                        params.append("rh=n%3A1389401031")
                    if min_price:
                        params.append(f"low-price={int(min_price)}")
                    if max_price:
                        params.append(f"high-price={int(max_price)}")
                    scan_urls.append(f"{self.domain}/s?{'&'.join(params)}")

        if progress_callback:
            progress_callback({
                "stage": "starting",
                "message": f"⚡ Turbo Engine: Concurrently scanning {len(scan_urls)} Amazon catalog pages...",
                "parsed": parsed,
                "current_page": 0,
                "total_pages": len(scan_urls),
            })

        t_start = time.time()
        logger.info(f"⚡ Turbo Engine: Scanning {len(scan_urls)} Amazon pages in parallel...")
        ensure_amazon_cookies()

        def _fetch_and_parse(u: str) -> List[Dict[str, Any]]:
            cmd = [
                CURL_BIN, "-s", "--compressed",
                "-b", str(COOKIE_FILE), "-c", str(COOKIE_FILE),
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                u
            ]
            for attempt in range(2):
                try:
                    html = subprocess.check_output(cmd, timeout=5).decode("utf-8", errors="ignore")
                except Exception:
                    try:
                        import urllib.request
                        req = urllib.request.Request(
                            u,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                                "Accept-Language": "en-US,en;q=0.9",
                            }
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            html = resp.read().decode("utf-8", errors="ignore")
                    except Exception:
                        html = ""

                if html and ('data-component-type="s-search-result"' in html or len(html) > 20000):
                    soup = BeautifulSoup(html, "html.parser")
                    items = soup.select("div[data-component-type='s-search-result']") or soup.select(".s-result-item[data-asin]")
                    page_items = []
                    for it in items:
                        p_data = self._parse_search_item_node(
                            it,
                            query=query,
                            target_brand=target_brand,
                            target_model=target_model,
                            is_phone_query=is_phone_query,
                            in_stock_only=in_stock_only,
                            min_price=min_price,
                            max_price=max_price,
                            prime_only=prime_only,
                            min_rating=min_rating,
                        )
                        if p_data:
                            page_items.append(p_data)
                    return page_items
                elif "bm-verify" in html:
                    ensure_amazon_cookies()
                time.sleep(0.1)
            return []

        with ThreadPoolExecutor(max_workers=min(len(scan_urls), 25)) as ex:
            pages_results = list(ex.map(_fetch_and_parse, scan_urls))

        seen_asins = set()
        results = []

        for p_items in pages_results:
            for it in p_items:
                if it["asin"] not in seen_asins:
                    seen_asins.add(it["asin"])
                    results.append(it)
                    if progress_callback:
                        progress_callback({
                            "stage": "item_scraped",
                            "item": it,
                            "total_count": len(results),
                        })

        elapsed_search = time.time() - t_start
        logger.info(f"⚡ Turbo Search finished in {elapsed_search:.2f}s! Found {len(results)} items.")

        if results:
            missing_sellers = [r for r in results if not r.get("seller") or r.get("seller") == "Amazon Verified"][:30]
            if missing_sellers:
                if progress_callback:
                    progress_callback({
                        "stage": "enriching_sellers",
                        "message": f"⚡ Quick-enriching sellers for {len(missing_sellers)} items...",
                        "current_page": len(scan_urls),
                        "total_pages": len(scan_urls),
                    })
                t_sel = time.time()
                with ThreadPoolExecutor(max_workers=min(len(missing_sellers), 25)) as ex:
                    sellers = list(ex.map(fetch_seller_for_asin, [r["asin"] for r in missing_sellers]))
                for r, s in zip(missing_sellers, sellers):
                    if s:
                        r["seller"] = s
                logger.info(f"⚡ Verified sellers enriched in {time.time()-t_sel:.2f}s!")

        if progress_callback:
            progress_callback({
                "stage": "completed",
                "message": f"⚡ Turbo Scraped {len(results)} verified items in {time.time()-t_start:.1f}s!",
                "total_count": len(results),
            })

        return results

    def scrape_search_results(
        self,
        query: str,
        max_pages: int = 1,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        in_stock_only: bool = True,
        prime_only: bool = False,
        min_rating: Optional[float] = None,
        progress_callback: Optional[Any] = None,
        deep_scan: bool = True,
        use_turbo: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Scrape product listings from Amazon search results with intelligent filters.
        Executes ultra-fast Turbo Engine first, with automatic browser fallback.
        """
        if use_turbo:
            try:
                turbo_res = self.scrape_search_results_turbo(
                    query=query,
                    max_pages=max_pages,
                    min_price=min_price,
                    max_price=max_price,
                    in_stock_only=in_stock_only,
                    prime_only=prime_only,
                    min_rating=min_rating,
                    progress_callback=progress_callback,
                    deep_scan=deep_scan,
                )
                if turbo_res and len(turbo_res) > 0:
                    return turbo_res
                logger.warning("Turbo search returned 0 items, checking browser driver fallback...")
            except Exception as e:
                logger.warning(f"Turbo search exception: {e}, checking browser driver fallback...")

        if not self.driver:
            logger.warning("No browser driver initialized. Returning turbo results.")
            return turbo_res if ('turbo_res' in locals() and turbo_res) else []

        parsed = parse_natural_query(query)
        actual_keyword = parsed["search_keyword"] or query
        target_brand = parsed.get("target_brand")
        target_model = parsed.get("target_model")

        if min_price is None and parsed.get("min_price") is not None:
            min_price = parsed["min_price"]
        if max_price is None and parsed.get("max_price") is not None:
            max_price = parsed["max_price"]

        is_phone_query = target_brand is not None or any(k in query.lower() for k in ("phone", "mobile", "smartphone", "pulse"))

        # Search queries generation
        search_queries = [actual_keyword]
        if target_brand:
            # Brand-specific angles only - strictly avoid injecting competitor brands
            if target_brand == "AI+":
                brand_angles = ["ai pulse 2", "ai+ pulse 2", "ai+ nova 5g", "ai+ pulse mobile"]
            elif target_brand == "Apple":
                brand_angles = ["apple iphone", "iphone 15", "iphone 16", "iphone 14"]
            elif target_brand == "Samsung":
                brand_angles = ["samsung galaxy smartphones", "samsung 5g mobile", "samsung galaxy s24 ultra"]
            elif target_brand == "OnePlus":
                brand_angles = ["oneplus smartphones", "oneplus nord ce 4", "oneplus 12"]
            elif target_brand == "Redmi":
                brand_angles = ["redmi smartphones", "redmi note 13 5g", "redmi 13c"]
            elif target_brand == "Realme":
                brand_angles = ["realme smartphones", "realme 12 pro 5g", "realme narzo"]
            elif target_brand == "Poco":
                brand_angles = [
                    "poco smartphones",
                    "poco 5g mobile",
                    "poco m6 5g",
                    "poco x6",
                    "poco c65",
                    "poco f6",
                    "poco c61",
                ]
            else:
                brand_angles = [f"{target_brand} smartphones", f"{target_brand} 5G mobile"]

            for ang in brand_angles:
                if ang.lower() not in [q.lower() for q in search_queries]:
                    search_queries.append(ang)
        elif deep_scan and is_phone_query:
            extras = [
                "ai pulse 2",
                f"smartphones under {int(max_price)}" if max_price else "smartphones",
                f"5G smartphones under {int(max_price)}" if max_price else "5G smartphones",
            ]
            for ext in extras:
                if ext.lower() not in [q.lower() for q in search_queries]:
                    search_queries.append(ext)

        results: List[Dict[str, Any]] = []
        seen_asins = set()

        brand_label = f" ({target_brand} Catalog)" if target_brand else ""
        if progress_callback:
            progress_callback({
                "stage": "starting",
                "message": f"Searching Amazon for '{actual_keyword}'{brand_label} ({len(search_queries)} search angles)...",
                "parsed": parsed,
                "current_page": 0,
                "total_pages": max_pages * len(search_queries),
            })

        total_steps = len(search_queries) * max_pages
        step = 0

        for cur_query in search_queries:
            for page in range(1, max_pages + 1):
                step += 1
                url_params = [f"k={cur_query.replace(' ', '+')}", f"page={page}"]
                if min_price is not None:
                    url_params.append(f"low-price={int(min_price)}")
                if max_price is not None:
                    url_params.append(f"high-price={int(max_price)}")

                search_url = f"{self.domain}/s?{'&'.join(url_params)}"
                logger.info(f"[{step}/{total_steps}] Scraping: {cur_query} (p.{page}): {search_url}")

                if progress_callback:
                    progress_callback({
                        "stage": "page_loading",
                        "message": f"Scanning Amazon angle '{cur_query}' (page {page})...",
                        "current_page": step,
                        "total_pages": total_steps,
                        "url": search_url,
                    })

                try:
                    self.driver.get(search_url)
                except TimeoutException:
                    logger.warning("Search page load timed out, trying to parse available content...")
                except WebDriverException as e:
                    logger.error(f"Search request failed: {e}")
                    break

                if not self.check_and_handle_captcha():
                    break

                self.random_sleep()

                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                items = soup.select("div[data-component-type='s-search-result']")
                if not items:
                    items = soup.select(".s-result-item[data-asin]")

                logger.info(f"Found {len(items)} raw listings for '{cur_query}' on page {page}.")

                page_items = 0
                for item in items:
                    asin = item.get("data-asin", "").strip()
                    if not asin or asin in seen_asins:
                        continue

                    # Title & URL
                    recipe = item.find("div", {"data-cy": "title-recipe"})
                    title = ""
                    full_url = ""

                    if recipe:
                        link_el = recipe.find("a", href=lambda h: h and ("/dp/" in h or "/gp/" in h)) or recipe.find("a")
                        if link_el:
                            href = link_el.get("href", "")
                            full_url = urljoin(self.domain, href)

                        # Detect separate brand sub-header (e.g. Amazon puts "POCO" in a separate mini header)
                        brand_sub = recipe.find("h2", class_=lambda c: c and "a-size-mini" in c) or recipe.select_one(".a-row.a-color-secondary span")
                        brand_header = clean_text(brand_sub.text) if brand_sub else ""

                        # Main product title
                        main_h2 = recipe.find("h2", class_=lambda c: c and "a-size-medium" in c) or recipe.find("h2", class_=lambda c: c and "a-color-base" in c) or recipe.find("h2")
                        if main_h2:
                            title = main_h2.get("aria-label") or clean_text(main_h2.text)
                        if not title and link_el:
                            title = link_el.get("aria-label") or clean_text(link_el.text)

                        # Combine brand header with title if not already present
                        if brand_header and brand_header.lower() not in title.lower():
                            title = f"{brand_header} {title}".strip()

                    if not title:
                        title_selectors = [
                            "div[data-cy='title-recipe'] h2 span",
                            "h2.a-color-base span",
                            "h2 a span",
                            "h2.a-size-medium.a-text-normal span",
                            "h2.a-text-normal",
                            "a.a-link-normal.s-link-style span",
                            "a.a-text-normal span",
                        ]
                        for t_sel in title_selectors:
                            t_el = item.select_one(t_sel)
                            if t_el and t_el.text:
                                candidate = clean_text(t_el.text)
                                if len(candidate) > 2:
                                    title = candidate
                                    break

                    if not full_url:
                        link_el = item.select_one("a[href*='/dp/']") or item.select_one("h2 a")
                        href = link_el["href"] if link_el and link_el.has_attr("href") else f"/dp/{asin}"
                        full_url = urljoin(self.domain, href)

                    # Price & MRP
                    price_text = ""
                    price_el = item.select_one(".a-price .a-offscreen")
                    if price_el:
                        price_text = clean_text(price_el.text)
                    price_num = parse_price(price_text)

                    mrp_text = ""
                    mrp_el = item.select_one(".a-price.a-text-price .a-offscreen")
                    if mrp_el:
                        mrp_text = clean_text(mrp_el.text)
                    mrp_num = parse_price(mrp_text)

                    # Strictly filter out accessories (covers, cases, tempered glass, smart watches, speakers) for phone queries
                    if is_phone_query and is_phone_accessory(title, price_num, target_brand):
                        continue

                    # Extract Brand and Tech Specifications early
                    brand_and_specs = extract_brand_and_specs(title)
                    brand = brand_and_specs["brand"]
                    specs = brand_and_specs["specs"]

                    # If user targeted a specific brand/model, reject competitor ads and off-brand sponsored products
                    if target_brand:
                        title_l = title.lower()
                        brand_match = False
                        if target_brand == "AI+":
                            if "ai+" in title_l or "ai pulse" in title_l or "pulse 2" in title_l or "ai nova" in title_l or brand == "AI+":
                                brand_match = True
                        elif target_brand == "Apple":
                            if "iphone" in title_l or "apple" in title_l or brand == "Apple":
                                brand_match = True
                        else:
                            if target_brand.lower() in title_l or (brand and brand.lower() == target_brand.lower()):
                                brand_match = True

                        if not brand_match:
                            continue

                        if target_model:
                            if not matches_exact_model(title, target_model):
                                continue

                    # Stock & Availability Detection
                    card_text = item.get_text().lower()
                    is_out_of_stock = (
                        "currently unavailable" in card_text
                        or "out of stock" in card_text
                        or "temporarily out of stock" in card_text
                    )
                    if price_num is None or price_num <= 0:
                        is_out_of_stock = True

                    in_stock = not is_out_of_stock
                    availability = "In stock" if in_stock else "Out of stock"

                    # Apply In-Stock Filter
                    if in_stock_only and not in_stock:
                        continue

                    # Apply Price Budget Filters (if specified)
                    if max_price is not None and price_num is not None and price_num > max_price:
                        continue
                    if min_price is not None and price_num is not None and price_num < min_price:
                        continue

                    # Prime filter
                    is_prime = bool(item.select_one(".a-icon-prime"))
                    if prime_only and not is_prime:
                        continue

                    # Rating & Reviews
                    rating = ""
                    rating_num = None
                    rating_el = item.select_one("i.a-icon-star-small span.a-icon-alt") or item.select_one("span.a-icon-alt")
                    if rating_el:
                        rating = clean_text(rating_el.text)
                        r_match = re.search(r"(\d+(?:\.\d+)?)", rating)
                        if r_match:
                            try:
                                rating_num = float(r_match.group(1))
                            except ValueError:
                                pass

                    if min_rating is not None and rating_num is not None and rating_num < min_rating:
                        continue

                    review_count = ""
                    reviews_el = item.select_one("span.a-size-base.s-underline-text") or item.select_one("span.s-underline-text")
                    if reviews_el:
                        review_count = clean_text(reviews_el.text)

                    # Image
                    img_el = item.select_one("img.s-image")
                    img_url = img_el["src"] if img_el and img_el.has_attr("src") else ""

                    # Discount
                    discount = ""
                    if price_num and mrp_num and mrp_num > price_num:
                        pct = round(((mrp_num - price_num) / mrp_num) * 100)
                        discount = f"-{pct}%"

                    # Check for badges
                    badge = ""
                    badge_el = item.select_one(".a-badge-text") or item.select_one(".s-ribbon-text")
                    if badge_el:
                        badge = clean_text(badge_el.text)

                    product_data = {
                        "asin": asin,
                        "title": title,
                        "price": price_text or (f"₹{price_num:,.2f}" if price_num else "N/A"),
                        "price_num": price_num,
                        "mrp": mrp_text,
                        "mrp_num": mrp_num,
                        "discount": discount,
                        "in_stock": in_stock,
                        "availability": availability,
                        "rating": rating,
                        "rating_num": rating_num,
                        "review_count": review_count,
                        "brand": brand,
                        "seller": "",
                        "is_prime": is_prime,
                        "delivery": "Prime Delivery" if is_prime else "",
                        "image_url": img_url,
                        "specs": specs,
                        "badge": badge,
                        "features": ", ".join(specs),
                        "search_query": query,
                        "url": full_url,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    seen_asins.add(asin)
                    results.append(product_data)
                    page_items += 1

                    if progress_callback:
                        progress_callback({
                            "stage": "item_scraped",
                            "item": product_data,
                            "total_count": len(results),
                        })

            logger.info(f"Page {page}: Scraped {page_items} valid items (Total matches so far: {len(results)})")

        # Concurrently enrich all scraped items with verified Amazon Seller information
        if results:
            if progress_callback:
                progress_callback({
                    "stage": "enriching_sellers",
                    "message": f"Fetching verified Amazon seller information for {len(results)} items...",
                    "current_page": total_steps,
                    "total_pages": total_steps,
                })
            logger.info(f"Enriching sellers for {len(results)} items via concurrent pool...")
            try:
                with ThreadPoolExecutor(max_workers=6) as executor:
                    sellers = list(executor.map(fetch_seller_for_asin, [r["asin"] for r in results]))
                for r, s in zip(results, sellers):
                    r["seller"] = s
            except Exception as e:
                logger.warning(f"Seller enrichment encountered minor issue: {e}")

        if progress_callback:
            progress_callback({
                "stage": "completed",
                "message": f"Successfully scraped {len(results)} in-stock items with verified sellers!",
                "total_count": len(results),
            })

        return results


STANDARD_FIELDS = [
    "asin",
    "title",
    "price",
    "price_num",
    "mrp",
    "mrp_num",
    "discount",
    "in_stock",
    "availability",
    "rating",
    "review_count",
    "brand",
    "seller",
    "is_prime",
    "delivery",
    "image_url",
    "features",
    "search_query",
    "url",
    "scraped_at",
]


class DataExporter:
    """Helper to export scraped data to CSV and JSON."""

    @staticmethod
    def save_to_csv(data: List[Dict[str, Any]], filepath: Path) -> None:
        if not data:
            return
        filepath.parent.mkdir(parents=True, exist_ok=True)
        file_exists = filepath.exists()
        with open(filepath, mode="a" if file_exists else "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=STANDARD_FIELDS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for row in data:
                # Ensure all standard keys exist
                clean_row = {k: row.get(k, "") for k in STANDARD_FIELDS}
                writer.writerow(clean_row)
        logger.info(f"[OK] Saved {len(data)} items to CSV: {filepath}")

    @staticmethod
    def save_to_json(data: List[Dict[str, Any]], filepath: Path) -> None:
        if not data:
            return
        filepath.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        # Merge deduplicating by ASIN
        seen_asins = {item.get("asin") for item in existing if item.get("asin")}
        for d in data:
            if d.get("asin") not in seen_asins:
                existing.append(d)
                if d.get("asin"):
                    seen_asins.add(d.get("asin"))

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing if existing else data, f, indent=2, ensure_ascii=False)
        logger.info(f"[OK] Saved to JSON: {filepath}")

    @staticmethod
    def print_summary_card(item: Dict[str, Any]) -> None:
        """Neatly print scraped product summary in terminal."""
        title = item.get("title") or "N/A"
        asin = item.get("asin") or "N/A"
        brand = item.get("brand") or "N/A"
        price = item.get("price") or "N/A"
        mrp = item.get("mrp") or "N/A"
        discount = item.get("discount") or "N/A"
        rating = item.get("rating") or "N/A"
        reviews = item.get("review_count") or "0 reviews"
        stock = item.get("availability") or "N/A"
        seller = item.get("seller") or ""
        url = item.get("url") or "N/A"

        print("\n" + "=" * 70)
        print(f" [PRODUCT]  {title[:65]}")
        print(f" [ASIN]     {asin}  |  [BRAND] {brand}")
        print(f" [PRICE]    {price}  |  [MRP] {mrp}  |  [DISCOUNT] {discount}")
        print(f" [RATING]   {rating} ({reviews})")
        print(f" [STOCK]    {stock}")
        if seller:
            print(f" [SELLER]   {seller[:65]}")
        print(f" [URL]      {url}")
        print("=" * 70)

