#!/usr/bin/env python3
"""Capture screenshots of the running app (started with --demo) for docs/media.

Usage: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 scripts/screenshots.py [base_url]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "media"


def shoot(page, path: Path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))
    print(f"saved {path}")


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18820"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)

        page.goto(f"{base_url}/", wait_until="networkidle")
        time.sleep(0.5)
        shoot(page, OUT_DIR / "notebook.png")

        page.click("text=Data")
        time.sleep(0.3)
        page.click("text=sales")
        time.sleep(0.6)
        shoot(page, OUT_DIR / "data.png")

        page.click("text=Units & dates")
        time.sleep(0.3)
        shoot(page, OUT_DIR / "units-dates.png")

        page.click("text=Statistics")
        time.sleep(0.3)
        page.select_option("select", "ttest_ind")
        shoot(page, OUT_DIR / "statistics.png")

        page.click("text=Work log")
        time.sleep(0.3)
        shoot(page, OUT_DIR / "work-log.png")

        browser.close()


if __name__ == "__main__":
    main()
