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
import sys
import logging
import time
import threading

import requests as _requests
from flask import Flask, make_response
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from salesforce_contract_monitor import initialize_session, check_for_changes

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


# ---------------------------------------------------------------------------
# Contract Status monitor — background thread
# ---------------------------------------------------------------------------

def _start_contract_monitor() -> None:
    thread = threading.Thread(target=_contract_monitor_loop, daemon=True, name="contract-monitor")
    thread.start()
    log.info("Contract status monitor thread started.")


def _contract_monitor_loop() -> None:
    POLL_INTERVAL = 15 * 60
    RETRY_DELAY   =  5 * 60

    while True:
        try:
            initialize_session()
            break
        except Exception as e:
            log.error("[monitor] Session init failed: %s — retrying in %d min",
                      e, RETRY_DELAY // 60, exc_info=True)
            time.sleep(RETRY_DELAY)

    while True:
        try:
            changes = check_for_changes()
            webhook_url = os.environ.get("TEAMS_CONTRACT_STATUS_WEBHOOK_URL", "")
            for change in changes:
                try:
                    card = _build_contract_status_card(change)
                    if not webhook_url:
                        log.error("[monitor] TEAMS_CONTRACT_STATUS_WEBHOOK_URL not set")
                        continue
                    resp = _requests.post(webhook_url, json={"adaptive_card": card}, timeout=10)
                    log.info("[monitor] Posted status change card for %s (HTTP %s)",
                             change["contract_no"], resp.status_code)
                except Exception as e:
                    log.error("[monitor] Failed to post card for %s: %s",
                              change.get("contract_no"), e)
        except Exception as e:
            log.error("[monitor] Poll error: %s", e, exc_info=True)

        log.info("[monitor] Sleeping %d minutes.", POLL_INTERVAL // 60)
        time.sleep(POLL_INTERVAL)


def _build_contract_status_card(change: dict) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "⚡ Contract Status Changed",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": change.get("account_name", "—"),
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "spacing": "Medium",
                "facts": [
                    {"title": "Contract No.",    "value": change.get("contract_no",  "—")},
                    {"title": "Created Date",    "value": change.get("created_date", "—")},
                    {"title": "Previous Status", "value": change.get("old_status",   "—")},
                    {"title": "New Status",      "value": change.get("new_status",   "—")},
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "View Contract",
                "url": change.get("url", ""),
                "style": "positive",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    log.info("Starting Contract Status monitor on port %d", port)
    log.info("GET /health — liveness check")
    _start_contract_monitor()
    app.run(host="0.0.0.0", port=port, debug=False)
