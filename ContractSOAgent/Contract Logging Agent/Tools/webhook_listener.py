"""
Tool: webhook_listener.py
Purpose: Teams ContractBot webhook and Power Automate confirmation callback.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from build_contract_card import (
    build_audit_card,
    build_contract_created_card,
    build_confirmation_card,
    build_navigation_success_card,
    prepare_contract_details,
)
from create_contract_in_portal import create_contract_in_portal
from fetch_jira_ticket import JiraAuthError, JiraConnectionError, fetch_jira_ticket
from navigate_contract_page import navigate_to_contract_page
from notify_teams import post_card, post_text


load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
TICKET_PATTERN = re.compile(r"\b(O360-\d+)\b", re.IGNORECASE)
BASE_DIR = Path(__file__).parent.parent
LOG_PATH = BASE_DIR / "Logs" / "error.log"
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"


@app.get("/health")
def health():
    return "OK", 200


@app.get("/")
def root():
    return jsonify({"service": "contract-logging-agent", "status": "ok"})


@app.post("/contract-webhook")
def contract_webhook():
    raw_body = request.get_data()
    token = os.getenv("TEAMS_CONTRACT_BOT_TOKEN", "")
    if not validate_hmac(raw_body, request.headers.get("Authorization", ""), token):
        return jsonify({"type": "message", "text": "HMAC validation failed."})

    body = request.get_json(force=True, silent=True) or {}
    message_text = extract_message_text(body)
    match = TICKET_PATTERN.search(message_text)
    if not match:
        return jsonify({"type": "message", "text": "Please send a Jira ticket like O360-15342."})

    ticket_id = match.group(1).upper()
    threading.Thread(target=process_ticket, args=(ticket_id,), daemon=True).start()
    return jsonify(
        {
            "type": "message",
            "text": (
                f"Processing contract creation for {ticket_id}. "
                "I will post the confirmation card to this channel shortly."
            ),
        }
    )


@app.post("/contract-confirm")
def contract_confirm():
    data = request.get_json(force=True, silent=True) or {}
    ticket_id = (data.get("ticket_id") or "").strip().upper()
    if not ticket_id:
        return jsonify({"status": "error", "detail": "missing ticket_id"}), 400

    write_memory_step("contract_confirm", "success", f"Confirmed details for {ticket_id}", data)
    post_card(build_audit_card(data))
    threading.Thread(target=create_contract_after_confirm, args=(ticket_id, data), daemon=True).start()
    return jsonify({"status": "ok"}), 200


def process_ticket(ticket_id: str) -> None:
    try:
        ticket = fetch_jira_ticket(ticket_id)
        if ticket is None:
            post_text(f"Ticket {ticket_id} was not found in Jira.")
            write_memory_step("fetch_jira_ticket", "failed", "Ticket not found", {"ticket_id": ticket_id})
            return

        details = prepare_contract_details(ticket)
        card = build_confirmation_card(details)
        post_card(card)
        write_memory_step(
            "post_confirmation_card",
            "success",
            f"Posted confirmation card for {ticket_id}",
            {"ticket_id": ticket_id, "details": details},
        )

    except (JiraAuthError, JiraConnectionError) as exc:
        handle_error("process_ticket", "JIRA_ERROR", str(exc), {"ticket_id": ticket_id})
        post_text(f"Could not fetch Jira ticket {ticket_id}: {exc}")
    except Exception as exc:
        handle_error("process_ticket", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        post_text(f"Unexpected error while processing {ticket_id}: {exc}")


def navigate_after_confirm(ticket_id: str) -> None:
    try:
        result = navigate_to_contract_page()
        post_card(build_navigation_success_card(ticket_id, result["url"]))
        write_memory_step(
            "navigate_contract_page",
            "success",
            f"Successfully navigated to Contract page for {ticket_id}",
            {"ticket_id": ticket_id, "url": result["url"]},
        )
    except Exception as exc:
        handle_error("navigate_contract_page", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        post_text(f"Could not navigate to Contract page for {ticket_id}: {exc}")


def create_contract_after_confirm(ticket_id: str, data: dict) -> None:
    try:
        contract_number = create_contract_in_portal(data, ticket_id)
        if not contract_number:
            raise RuntimeError("Generated Contract Number was not captured after Save")
        post_card(build_contract_created_card(ticket_id, contract_number))
        write_memory_step(
            "create_contract_in_portal",
            "success",
            f"Created contract {contract_number} for {ticket_id} on JSW Steel Community SF portal",
            {"ticket_id": ticket_id, "contract_number": contract_number, "input": data},
        )
    except Exception as exc:
        handle_error("create_contract_in_portal", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        post_text(f"Could not create contract for {ticket_id}: {exc}")


def validate_hmac(body: bytes, auth_header: str, token: str = "") -> bool:
    if not token:
        return True
    if not auth_header.startswith("HMAC "):
        return False
    try:
        key = base64.b64decode(token)
    except Exception:
        return False
    expected = base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(auth_header[5:], expected)


def extract_message_text(body: dict) -> str:
    raw = body.get("text", "") or ""
    text = re.sub(r"<[^>]+>", " ", raw).strip()
    if text:
        return text
    for attachment in body.get("attachments", []):
        content = attachment.get("content", "")
        if isinstance(content, str) and content:
            return re.sub(r"<[^>]+>", " ", content).strip()
    return ""


def handle_error(step: str, code: str, message: str, payload: dict) -> None:
    entry = {
        "timestamp": utc_now(),
        "run_id": "contract_logging_runtime",
        "skill": "Contract Logging Agent",
        "tool": "webhook_listener.py",
        "step": step,
        "error_code": code,
        "error_message": message,
        "input_payload": payload,
        "context": step,
        "resolution_attempted": None,
        "resolution_status": "pending",
        "learning": None,
        "ticket_id": payload.get("ticket_id"),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry) + "\n")


def write_memory_step(step: str, status: str, detail: str, extra: dict | None = None) -> None:
    memory = read_memory()
    history = memory.setdefault("state", {}).setdefault("run_history", [])
    history.append(
        {
            "step": step,
            "status": status,
            "detail": detail,
            "timestamp": utc_now(),
            "extra": extra or {},
        }
    )
    memory["last_run"] = utc_now()
    memory["last_action"] = detail
    MEMORY_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")


def read_memory() -> dict:
    if MEMORY_PATH.exists():
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    return {
        "skill": "Contract Logging Agent",
        "last_run": None,
        "last_action": None,
        "state": {"pending_items": [], "completed_items": [], "run_history": []},
        "known_issues": [],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    port = int(os.getenv("PORT") or os.getenv("FLASK_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
