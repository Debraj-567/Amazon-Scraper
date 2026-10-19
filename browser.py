#!/usr/bin/env python3
"""
Chrome browser manager for Amazon scraper.
Provides persistent profiles and anti-detection flags mirroring Flip-Kart setup.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except ImportError:
    webdriver = None
    Options = None
    Service = None

BASE_DIR = Path(__file__).resolve().parent
CHROME_BINARY = os.environ.get("CHROME_BINARY")


def detect_chrome_binary() -> str:
    """Find installed Google Chrome binary on Windows systems."""
    if CHROME_BINARY and os.path.isfile(CHROME_BINARY):
        return CHROME_BINARY

    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for r in roots:
        if not r:
            continue
        p = os.path.join(r, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.isfile(p):
            return p
    return ""


def build_chrome_options(
    profile_path: Path,
    headless: bool = False,
    user_agent: Optional[str] = None,
    stealth: bool = True,
) -> Options:
    """Create Chrome options with anti-bot evasion and persistent profile."""
    options = Options()
    binary = detect_chrome_binary()
    if binary:
        options.binary_location = binary

    profile_path.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_path.resolve()}")
    options.add_argument("--profile-directory=Default")

    if headless:
        # Modern headless flag avoids easy bot detection
        options.add_argument("--headless=new")

    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--window-size=1380,940")
    options.add_argument("--lang=en-IN")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--remote-allow-origins=*")

    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")

    if stealth:
        # Anti-detection flags mirroring Flip-Kart main.py
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    return options


def get_driver(
    profiles_dir: Path,
    profile_name: str = "default_profile",
    headless: bool = False,
    user_agent: Optional[str] = None,
    stealth: bool = True,
) -> webdriver.Chrome:
    """Initialize Selenium WebDriver with stealth and persistent profile."""
    pdir = profiles_dir / profile_name
    options = build_chrome_options(
        profile_path=pdir,
        headless=headless,
        user_agent=user_agent,
        stealth=stealth,
    )

    driver = webdriver.Chrome(options=options)

    if stealth:
        # In-browser stealth JS injection: override navigator.webdriver & plugins
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        window.navigator.chrome = {
                            runtime: {},
                        };
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5]
                        });
                    """
                },
            )
        except Exception:
            pass

    return driver


def reset_profile(profiles_dir: Path, profile_name: str = "default_profile") -> bool:
    """Clear saved profile cookies and state."""
    pdir = profiles_dir / profile_name
    if pdir.exists():
        try:
            shutil.rmtree(pdir)
            return True
        except Exception as e:
            print(f"[!] Error resetting profile: {e}")
            return False
    return False
