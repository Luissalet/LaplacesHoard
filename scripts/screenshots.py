#!/usr/bin/env python3
"""Capture the README screenshots from a running demo instance.

1. start the app:      .venv/bin/python -m laplaces_hoard --demo --no-browser --port 18820
2. real agent calls:   .venv/bin/python scripts/demo_agent_session.py http://127.0.0.1:18820
3. screenshots:        PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 scripts/screenshots.py http://127.0.0.1:18820

Step 3 needs a Python with playwright and Pillow whose browser build matches
PLAYWRIGHT_BROWSERS_PATH (playwright is not an app dependency). Images are
1440x900 at scale 1, saved as optimised PNGs under docs/media (< 400 KB each).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "media"
MAX_BYTES = 400_000


def shoot(page, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    page.screenshot(path=str(path))
    img = Image.open(path)
    img.save(path, optimize=True)
    if path.stat().st_size > MAX_BYTES:  # fall back to a 256-colour palette
        img.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    print(f"saved {path.relative_to(REPO_ROOT)} ({path.stat().st_size // 1024} KB)")


def nav(page, label: str) -> None:
    page.click(f".sidebar .nav-item:has-text('{label}')")
    time.sleep(0.5)


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18820"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="en-GB")
        page = ctx.new_page()
        page.add_init_script("localStorage.setItem('lh_lang', 'en'); localStorage.setItem('lh_theme', 'light');")

        page.goto(f"{base_url}/", wait_until="networkidle")
        time.sleep(0.8)
        shoot(page, "notebook.png")

        # Data: dataset profile, a grouped query and a chart of its result
        nav(page, "Data")
        page.click(".dataset-item >> text=sales")
        time.sleep(0.8)
        page.fill("textarea.sql-editor",
                  "SELECT region, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS revenue\n"
                  "FROM sales\nGROUP BY region\nORDER BY revenue DESC")
        page.click("button:has-text('Run')")
        page.wait_for_selector("text=of 5 rows")
        page.fill("#chart-builder input[type=text]", "Revenue by region")
        page.select_option("#chart-builder select >> nth=2", "revenue")
        page.click("button:has-text('Build chart')")
        page.wait_for_selector(".chart-frame canvas, .chart-frame svg", timeout=15000)
        time.sleep(1.0)
        page.evaluate("document.querySelector('.main').scrollTo(0, 0)")
        # The dataset's source path is absolute and machine-specific; show it
        # relative to a neutral checkout folder instead.
        page.evaluate(r"""() => {
            for (const el of document.querySelectorAll('.mono[title]')) {
                el.textContent = el.textContent.replace(/^.*(?=[\\/]data-demo[\\/])/, '~/LaplacesHoard');
            }
        }""")
        shoot(page, "data.png")
        page.evaluate("document.querySelector('.main').scrollTo(0, 100000)")
        time.sleep(0.4)
        shoot(page, "data-chart.png")

        # Statistics: Welch's t-test on two regions of the sales dataset
        nav(page, "Statistics")
        page.click("button:has-text('Use a dataset')")
        page.select_option(".grid-form-result select >> nth=1", "sales")
        page.select_option(".grid-form-result select >> nth=2", "amount")
        page.select_option(".grid-form-result select >> nth=3", "region")
        page.fill("input[placeholder=\"region = 'North'\"]", "region IN ('North', 'South')")
        page.click("button:has-text('Run test')")
        page.wait_for_selector(".interpretation")
        time.sleep(0.4)
        shoot(page, "statistics.png")

        # Units & dates: a conversion and a Madrid business-day count
        nav(page, "Units & dates")
        page.click("button.chip:has-text('100 degF')")
        page.click("button:has-text('Compute')")
        page.wait_for_selector(".headline-unit:has-text('business days')")
        time.sleep(0.4)
        shoot(page, "units-dates.png")

        # What the assistant did (real MCP calls from demo_agent_session.py)
        nav(page, "Assistant activity")
        time.sleep(0.6)
        shoot(page, "assistant-activity.png")

        # Settings: the Models panel (the shared backend's resolution + reason)
        nav(page, "Settings")
        time.sleep(0.4)
        shoot(page, "settings-models.png")

        browser.close()


if __name__ == "__main__":
    main()
