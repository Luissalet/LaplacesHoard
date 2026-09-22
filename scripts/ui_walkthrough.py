#!/usr/bin/env python3
"""Walk the person use cases of docs/USE_CASES.md in a real browser.

Drives the running app with Playwright, step by step, the way a person
would, and saves a screenshot at each key moment (read them - that is the
point) plus a timing and console-error log.

Usage (app running on a fresh --data-dir, data from scripts/uxtest_data.py):
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 scripts/ui_walkthrough.py \
        http://127.0.0.1:18820 data-uxtest/files data-uxtest/shots
Needs a Python with playwright (not an app dependency).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


class Run:
    def __init__(self, page: Page, out: Path):
        self.page, self.out = page, out
        self.console: list[str] = []
        self.n = 0
        page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))

    def shot(self, name: str, full: bool = False) -> None:
        self.n += 1
        path = self.out / f"{self.n:02d}-{name}.png"
        self.page.screenshot(path=str(path), full_page=full)
        print(f"  shot {path.name}")

    def step(self, text: str) -> None:
        print(f"- {text}")

    def timed(self, text: str, fn) -> float:
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        print(f"  {text}: {dt * 1000:.0f} ms")
        return dt

    def nav(self, label: str) -> None:
        self.page.click(f".sidebar .nav-item:has-text('{label}')")
        time.sleep(0.4)

    def text_of(self, sel: str) -> str:
        try:
            return self.page.locator(sel).first.inner_text(timeout=3000)
        except Exception as exc:  # noqa: BLE001
            return f"<{type(exc).__name__}>"


def register(r: Run, path: Path, delimiter: str = "", name: str = "") -> None:
    p = r.page
    if not p.locator("input[placeholder^='C:']").count():
        p.click(".card-head .icon-btn")
    p.fill("input[placeholder^='C:']", str(path))
    if name:
        p.locator("input[placeholder^='C:'] >> xpath=../following-sibling::div[1]//input").fill(name)
    if delimiter:
        p.fill("input[placeholder=', ; |']", delimiter)
    btn = p.locator("button.btn:has-text('Registr'), button.btn:has-text('Register')").first
    def go():
        with p.expect_response(lambda resp: "/api/ui/data_register" in resp.url, timeout=60000) as info:
            btn.click()
        print(f"  register -> HTTP {info.value.status}")
        time.sleep(0.8)
    r.timed(f"register {path.name}", go)


def run_sql(r: Run, sql: str) -> None:
    p = r.page
    p.fill("textarea.sql-editor", sql)
    r.timed("query", lambda: (p.keyboard.press("Control+Enter") if p.focus("textarea.sql-editor") is None else None,
                              time.sleep(0.8)))


def uc1_bank_es(r: Run, files: Path) -> None:
    p = r.page
    r.step("UC1 (persona, ES): first run, then '¿en qué se me va el dinero?' with the bank export")
    p.goto(r.base, wait_until="networkidle")
    time.sleep(0.6)
    r.shot("es-first-run-notebook")
    r.nav("Datos")
    r.shot("es-data-empty")
    p.click(".card-head .icon-btn")
    time.sleep(0.3)
    r.shot("es-add-dataset-form")
    register(r, files / "movimientos_2023-2025.csv")
    r.shot("es-bank-registered")
    r.shot("es-bank-registered-full", full=True)
    run_sql(r, 'SELECT "Categoría", SUM("Importe (€)") AS total\nFROM movimientos_2023_2025\nGROUP BY 1 ORDER BY 2')
    r.shot("es-bank-sum-varchar-error")
    run_sql(r, 'SELECT "Categoría", -SUM(CAST(replace(replace("Importe (€)", \'.\', \'\'), \',\', \'.\') AS DECIMAL(12,2))) AS gasto\n'
               'FROM movimientos_2023_2025\nWHERE year("Fecha operación") = 2025 AND "Categoría" <> \'Nómina\'\nGROUP BY 1 ORDER BY 2 DESC')
    r.shot("es-bank-sum-fixed")
    # chart it
    try:
        p.locator("#chart-builder select").nth(2).select_option("gasto")
        p.click("button:has-text('Crear gráfico'), button:has-text('Build chart')")
        p.wait_for_selector(".chart-frame canvas, .chart-frame svg", timeout=15000)
        time.sleep(0.8)
        p.evaluate("document.querySelector('.main').scrollTo(0, 100000)")
        time.sleep(0.3)
        r.shot("es-bank-chart")
    except Exception as exc:  # noqa: BLE001
        print(f"  chart failed: {exc}")
        r.shot("es-bank-chart-failed")
    # export
    try:
        with p.expect_download(timeout=10000) as dl:
            p.click("button:has-text('Exportar CSV'), button:has-text('Export CSV')")
        d = dl.value
        target = r.out / f"export-{d.suggested_filename}"
        d.save_as(str(target))
        head = target.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
        print(f"  export saved {target.name}: {head}")
    except Exception as exc:  # noqa: BLE001
        print(f"  export failed: {exc}")
    # Windows-1252 export from another bank
    p.evaluate("document.querySelector('.main').scrollTo(0, 0)")
    register(r, files / "latin1.csv")
    r.shot("es-cp1252-error")
    # re-register (refresh after downloading a new month)
    register(r, files / "movimientos_2023-2025.csv", delimiter=";")
    r.shot("es-reregister-error")


def uc4_writing_en(r: Run, files: Path) -> None:
    p = r.page
    r.step("UC4 (person, EN): novel pace - words per month and when do I reach 90,000 words")
    p.evaluate("localStorage.setItem('lh_lang', 'en')")
    p.goto(r.base, wait_until="networkidle")
    r.nav("Data")
    register(r, files / "sesiones_escritura.csv")
    run_sql(r, "SELECT strftime(date, '%Y-%m') AS month, SUM(words) AS words, ROUND(SUM(words) / (SUM(minutes) / 60.0)) AS words_per_hour\n"
               "FROM sesiones_escritura GROUP BY 1 ORDER BY 1")
    try:
        p.locator("#chart-builder select").nth(0).select_option("line")
        p.locator("#chart-builder select").nth(2).select_option("words")
        p.click("button:has-text('Build chart')")
        p.wait_for_selector(".chart-frame canvas, .chart-frame svg", timeout=15000)
        time.sleep(0.6)
    except Exception as exc:  # noqa: BLE001
        print(f"  chart failed: {exc}")
    r.shot("en-writing-month", full=True)
    run_sql(r, "SELECT SUM(words) AS total, COUNT(*) AS sessions, MAX(date) AS last FROM sesiones_escritura")
    total = r.text_of("table:has(th:text-is('total')) tbody tr td")
    print(f"  total words so far: {total}")
    r.nav("Notebook")
    for engine, text in (("calc", f"(90000 - {total.replace('.', '').replace(',', '').strip() or 0}) / 350"),
                         ("dates", "today"), ("calc", "1.000 * 3"), ("calc", "3,5 + 2"), ("calc", "pct(21, 1234,56)"),
                         ("units", "3,5 km -> mi"), ("math", "x^2 - 5x + 6 = 0")):
        p.click(f".pill-select button:has-text('{engine}')")
        p.fill("input.grow.mono", text)
        r.timed(f"notebook {engine}: {text}", lambda: (p.keyboard.press("Enter"), time.sleep(0.9)))
    r.shot("en-notebook-cells", full=True)


def uc6_quick_es(r: Run, files: Path) -> None:
    p = r.page
    r.step("UC6 (persona, ES): IVA, costume measurements and a Madrid deadline")
    p.evaluate("localStorage.setItem('lh_lang', 'es')")
    p.goto(r.base, wait_until="networkidle")
    r.nav("Unidades y fechas")
    r.shot("es-units-dates")
    inputs = p.locator(".card").first.locator("input[type=text]")
    inputs.nth(0).fill("3,5 km")
    inputs.nth(1).fill("mi")
    p.locator(".card").first.locator("button.btn").click()
    time.sleep(0.8)
    r.shot("es-units-comma")
    inputs.nth(0).fill("72 pulgadas")
    inputs.nth(1).fill("cm")
    p.locator(".card").first.locator("button.btn").click()
    time.sleep(0.8)
    r.shot("es-units-spanish-name")
    # dates: business days
    sel = p.locator("select").first
    sel.select_option("business_days")
    time.sleep(0.2)
    card = p.locator(".card").nth(1)
    ins = card.locator("input[type=text]")
    ins.nth(0).fill("hoy")
    ins.nth(1).fill("30/10/2026")
    card.locator("button.btn").click()
    time.sleep(1.0)
    r.shot("es-business-days")


def uc3_stats_es(r: Run, files: Path) -> None:
    p = r.page
    r.step("UC3 (persona, ES): job-hunt workbook, Fisher's test in the UI and pasted Spanish decimals")
    r.nav("Datos")
    register(r, files / "busqueda_empleo_2026.xlsx")
    r.shot("es-xlsx-registered")
    try:
        p.click(".dataset-item >> text=Entrevistas")
        time.sleep(0.6)
        r.shot("es-xlsx-title-row-sheet")
    except Exception as exc:  # noqa: BLE001
        print(f"  no Entrevistas item: {exc}")
    r.nav("Estadística")
    p.locator("select").first.select_option("fisher_exact")
    p.fill("textarea", "11, 36\n19, 30")
    p.click("button:has-text('Ejecutar prueba'), button:has-text('Run test')")
    time.sleep(1.0)
    r.shot("es-fisher")
    p.locator("select").first.select_option("describe")
    p.fill("textarea", "3,5; 4,2; 5,1; 6,0")
    p.click("button:has-text('Ejecutar prueba'), button:has-text('Run test')")
    time.sleep(1.0)
    r.shot("es-describe-decimal-commas")


def uc_log_activity(r: Run) -> None:
    p = r.page
    r.step("Work log / assistant activity: find the entry an agent cited")
    r.nav("Registro de cálculos")
    r.shot("es-worklog")
    p.fill("input[placeholder='Buscar']", "L-000003")
    time.sleep(0.8)
    r.shot("es-worklog-search-id")
    r.nav("Actividad del asistente")
    r.shot("es-activity")
    r.nav("Ajustes")
    time.sleep(1.0)
    r.shot("es-settings", full=True)


def keyboard_and_sizes(r: Run) -> None:
    p = r.page
    r.step("Keyboard: Tab from the top of the page; sizes 1280x800 and 1920x1080")
    p.goto(r.base, wait_until="networkidle")
    for _ in range(4):
        p.keyboard.press("Tab")
    focused = p.evaluate("document.activeElement && (document.activeElement.innerText || document.activeElement.tagName)")
    print(f"  4x Tab lands on: {focused!r}")
    r.shot("keyboard-focus")
    for w, h in ((1280, 800), (1920, 1080)):
        p.set_viewport_size({"width": w, "height": h})
        r.nav("Datos")
        try:
            p.click(".dataset-item >> text=movimientos", timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.6)
        r.shot(f"size-{w}x{h}-data")
    p.set_viewport_size({"width": 390, "height": 844})
    time.sleep(0.4)
    r.shot("size-390-mobile")


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18820"
    files = Path(sys.argv[2] if len(sys.argv) > 2 else REPO_ROOT / "data-uxtest" / "files").resolve()
    out = Path(sys.argv[3] if len(sys.argv) > 3 else REPO_ROOT / "data-uxtest" / "shots")
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="es-ES", accept_downloads=True)
        page = ctx.new_page()
        r = Run(page, out)
        r.base = base + "/"
        for fn in (lambda: uc1_bank_es(r, files), lambda: uc4_writing_en(r, files), lambda: uc6_quick_es(r, files),
                   lambda: uc3_stats_es(r, files), lambda: uc_log_activity(r), lambda: keyboard_and_sizes(r)):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                print(f"  !! step crashed: {type(exc).__name__}: {str(exc)[:300]}")
                try:
                    r.shot("crash")
                except Exception:  # noqa: BLE001
                    pass
        browser.close()
    print("console errors/warnings:")
    for line in r.console:
        print(f"  {line[:300]}")
    if not r.console:
        print("  none")


if __name__ == "__main__":
    main()
