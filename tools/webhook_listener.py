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
    while True:
        log.info("[monitor] Spawning monitor subprocess: %s", script)
        try:
            proc = subprocess.Popen([sys.executable, script])
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
