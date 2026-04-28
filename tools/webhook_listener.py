"""
Project : Contract Status
Tool    : webhook_listener.py
Purpose : Starts the Salesforce contract monitor background thread.
          Polls Salesforce every 15 minutes; posts an Adaptive Card to the
          Teams 'Contract Status' channel on every status change.

Routes:
    GET /health  — liveness check

Usage:
    python tools/webhook_listener.py
"""

import os
import logging
import time
import threading

from flask import Flask, make_response
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


@app.before_request
def log_requests():
    from flask import request
    log.info(">>> %s %s", request.method, request.path)


# ---------------------------------------------------------------------------
# Route: Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return make_response("OK", 200)


@app.route("/screenshot", methods=["GET"])
def screenshot():
    """Navigate to Salesforce login and return a screenshot so you can see what Chromium sees."""
    import base64, asyncio
    from flask import make_response as _make_response
    from playwright.sync_api import sync_playwright as _pw
    asyncio.set_event_loop(asyncio.new_event_loop())
    try:
        pw  = _pw().start()
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = ctx.new_page()
        sf_url = os.environ.get("SALESFORCE_URL", "https://jswsteel.my.site.com/jswone/s/login")
        page.goto(sf_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)

        title   = page.title()
        url     = page.url
        text    = (page.evaluate("() => document.body.innerText") or "").strip()[:800]
        png_b64 = base64.b64encode(page.screenshot(full_page=True)).decode()

        browser.close()
        pw.stop()

        html = f"""<!DOCTYPE html><html><head><title>Salesforce Screenshot</title></head><body>
<b>URL:</b> {url}<br><b>Title:</b> {title}<br>
<pre style="background:#f5f5f5;padding:8px;white-space:pre-wrap">{text}</pre>
<img src="data:image/png;base64,{png_b64}" style="max-width:100%;border:1px solid #ccc">
</body></html>"""
        resp = _make_response(html, 200)
        resp.headers["Content-Type"] = "text/html"
        return resp
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/test-login", methods=["GET"])
def test_login():
    """Fill Salesforce credentials and screenshot what happens after clicking Login."""
    import base64, asyncio, os as _os
    from flask import make_response as _make_response
    from playwright.sync_api import sync_playwright as _pw
    asyncio.set_event_loop(asyncio.new_event_loop())
    steps = []
    try:
        pw  = _pw().start()
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = ctx.new_page()
        sf_url  = _os.environ.get("SALESFORCE_URL", "")
        sf_user = _os.environ.get("SALESFORCE_USERNAME", "")
        sf_pass = _os.environ.get("SALESFORCE_PASSWORD", "")

        page.goto(sf_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
        steps.append(("After page load", page.url, base64.b64encode(page.screenshot()).decode()))

        page.wait_for_selector('input[placeholder="Username"]', timeout=30_000)
        page.locator('input[placeholder="Username"]').fill(sf_user)
        page.locator('input[type="password"]').fill(sf_pass)
        steps.append(("After filling credentials", page.url, base64.b64encode(page.screenshot()).decode()))

        for sel in ['button:has-text("Log in")', 'button:has-text("Login")', 'button[type="submit"]']:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2_000):
                    btn.click()
                    break
            except Exception:
                continue

        page.wait_for_timeout(8_000)
        steps.append(("8s after clicking Login", page.url, base64.b64encode(page.screenshot()).decode()))

        browser.close()
        pw.stop()

        imgs = "".join(
            f"<h3>{label}</h3><p>URL: {url}</p>"
            f'<img src="data:image/png;base64,{b64}" style="max-width:100%;border:1px solid #ccc;margin-bottom:20px"><br>'
            for label, url, b64 in steps
        )
        resp = _make_response(f"<!DOCTYPE html><html><body>{imgs}</body></html>", 200)
        resp.headers["Content-Type"] = "text/html"
        return resp
    except Exception as e:
        return {"error": str(e), "steps_completed": [s[0] for s in steps]}, 500


@app.route("/test-browser", methods=["GET"])
def test_browser():
    import time as _time
    from playwright.sync_api import sync_playwright
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    results = {}
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page()

        # Test 1: Google — confirms Chromium launches and internet works
        t0 = _time.time()
        try:
            page.goto("https://www.google.com", wait_until="commit", timeout=30_000)
            results["google"] = {"ok": True, "title": page.title(), "ms": int((_time.time() - t0) * 1000)}
        except Exception as e:
            results["google"] = {"ok": False, "error": str(e)}

        # Test 2: Salesforce login page — confirms if GCP IP is blocked
        t0 = _time.time()
        try:
            page.goto("https://jswsteel.my.site.com/jswone/s/login", wait_until="commit", timeout=60_000)
            results["salesforce"] = {"ok": True, "url": page.url, "ms": int((_time.time() - t0) * 1000)}
        except Exception as e:
            results["salesforce"] = {"ok": False, "error": str(e)}

        browser.close()
        pw.stop()
    except Exception as e:
        results["chromium_launch"] = {"ok": False, "error": str(e)}

    return results


# ---------------------------------------------------------------------------
# Contract Status monitor — subprocess watcher
# ---------------------------------------------------------------------------
# Running Playwright Sync API inside a threading.Thread fails on Cloud Run
# because Flask's startup leaves a running asyncio loop that Playwright
# detects and rejects.  A subprocess has a completely clean asyncio state,
# so it never hits that check.
# ---------------------------------------------------------------------------

def _start_contract_monitor() -> None:
    thread = threading.Thread(target=_monitor_watcher, daemon=True, name="monitor-watcher")
    thread.start()
    log.info("Contract status monitor watcher started.")


def _monitor_watcher() -> None:
    import subprocess, sys
    script = os.path.join(os.path.dirname(__file__), "salesforce_contract_monitor.py")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"   # ensure subprocess logs flush immediately
    while True:
        log.info("[monitor] Spawning monitor subprocess: %s", script)
        try:
            proc = subprocess.Popen([sys.executable, "-u", script], env=env)
            proc.wait()
            log.error("[monitor] Monitor subprocess exited (rc=%d) — restarting in 30 s.",
                      proc.returncode)
        except Exception as e:
            log.error("[monitor] Failed to start monitor subprocess: %s — retrying in 30 s.", e)
        time.sleep(30)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "8080"))
    log.info("Starting Contract Status monitor on port %d", port)
    log.info("GET /health — liveness check")
    _start_contract_monitor()
    app.run(host="0.0.0.0", port=port, debug=False)
