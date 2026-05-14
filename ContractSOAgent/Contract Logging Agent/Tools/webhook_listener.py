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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from build_contract_card import (
    build_audit_card,
    build_contract_creation_failed_card,
    build_contract_validation_failed_card,
    build_contract_created_card,
    build_confirmation_card,
    build_hrc_sku_confirmed_card,
    build_hrc_sku_details_card,
    build_hrc_sku_row_choice_card,
    build_hrc_sku_selection_card,
    build_hrc_sku_validation_failed_card,
    build_navigation_success_card,
    prepare_contract_details,
    build_sku_card,
    build_sku_success_card,
    build_sku_failure_card,
)
from contract_memory import (
    find_contract_context,
    get_sku_pending_request,
    save_sku_pending_request,
    store_confirmed_hrc_sku,
)
from create_contract_in_portal import create_contract_in_portal
from fetch_jira_ticket import JiraAuthError, JiraConnectionError, fetch_jira_ticket
from hrc_master_lookup import get_sku_choices, get_sku_details
from navigate_contract_page import navigate_to_contract_page
from notify_teams import post_card, post_text, post_sku_card


load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
TICKET_PATTERN = re.compile(r"\b(O360-\d+)\b", re.IGNORECASE)
CONTRACT_PATTERN = re.compile(r"\b(\d{7,9})\b")
BASE_DIR = Path(__file__).parent.parent
# /app is read-only in Cloud Run — use /tmp for local files
LOG_PATH = Path("/tmp/error.log") if os.environ.get("GCS_MEMORY_BUCKET") else BASE_DIR / "Logs" / "error.log"
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"

GCS_BUCKET = os.environ.get("GCS_MEMORY_BUCKET", "").strip()
GCS_MEMORY_BLOB = "contract-logging-agent/memory.json"

_MEMORY_DEFAULT = {
    "skill": "Contract Logging Agent",
    "last_run": None,
    "last_action": None,
    "state": {"pending_items": [], "completed_items": [], "run_history": []},
    "known_issues": [],
    "errors": [],
    "successes": [],
}


def _gcs_client():
    try:
        from google.cloud import storage
        return storage.Client()
    except Exception:
        return None


def _read_gcs_memory() -> dict:
    if not GCS_BUCKET:
        return dict(_MEMORY_DEFAULT)
    try:
        client = _gcs_client()
        if not client:
            return dict(_MEMORY_DEFAULT)
        blob = client.bucket(GCS_BUCKET).blob(GCS_MEMORY_BLOB)
        if not blob.exists():
            return dict(_MEMORY_DEFAULT)
        return json.loads(blob.download_as_text())
    except Exception:
        app.logger.exception("Could not read GCS memory")
        return dict(_MEMORY_DEFAULT)


def _write_gcs_memory(data: dict) -> None:
    if not GCS_BUCKET:
        return
    try:
        client = _gcs_client()
        if not client:
            return
        blob = client.bucket(GCS_BUCKET).blob(GCS_MEMORY_BLOB)
        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
    except Exception:
        app.logger.exception("Could not write GCS memory")


def record_contract_error(ticket_id: str, data: dict, error_message: str) -> None:
    memory = _read_gcs_memory()
    memory.setdefault("errors", []).append({
        "timestamp": utc_now(),
        "ticket_id": ticket_id,
        "contract_type": data.get("contract_type"),
        "distribution_channel": data.get("distribution_channel"),
        "division": data.get("division"),
        "error_message": error_message[:500],
        "resolved": False,
    })
    memory["errors"] = memory["errors"][-200:]
    _write_gcs_memory(memory)


def record_contract_success(ticket_id: str, data: dict, contract_number: str) -> None:
    memory = _read_gcs_memory()
    memory.setdefault("successes", []).append({
        "timestamp": utc_now(),
        "ticket_id": ticket_id,
        "contract_type": data.get("contract_type"),
        "distribution_channel": data.get("distribution_channel"),
        "division": data.get("division"),
        "contract_number": contract_number,
        "input": data,
    })
    for entry in memory.get("errors", []):
        if entry.get("ticket_id") == ticket_id and not entry.get("resolved"):
            entry["resolved"] = True
    memory["successes"] = memory["successes"][-200:]
    _write_gcs_memory(memory)


def check_past_errors(ticket_id: str, data: dict) -> list:
    """Return unresolved GCS memory errors matching this contract_type + distribution_channel."""
    try:
        memory = _read_gcs_memory()
        contract_type = (data.get("contract_type") or "").strip()
        dist_channel  = (data.get("distribution_channel") or "").strip()
        return [
            e for e in memory.get("errors", [])
            if not e.get("resolved")
            and e.get("contract_type") == contract_type
            and e.get("distribution_channel") == dist_channel
        ]
    except Exception:
        return []


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

    def _bg():
        with app.app_context():
            process_ticket(ticket_id)

    threading.Thread(target=_bg, daemon=True).start()

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
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    ticket_id = (data.get("ticket_id") or "").strip().upper()
    if not ticket_id:
        return jsonify({"status": "error", "detail": "missing ticket_id"}), 400

    app.logger.info("Contract confirm received for %s", ticket_id)
    missing_fields = validate_confirmed_contract_details(data)
    if missing_fields:
        app.logger.info("Contract confirm rejected for %s; missing fields: %s", ticket_id, ", ".join(missing_fields))
        post_card(build_contract_validation_failed_card(ticket_id, missing_fields))
        safe_write_memory_step(
            "contract_confirm_validation",
            "failed",
            f"Rejected confirmation for {ticket_id}; missing required fields: {', '.join(missing_fields)}",
            {"ticket_id": ticket_id, "missing_fields": missing_fields, "input": data},
        )
        return jsonify({"status": "validation_error", "ticket_id": ticket_id, "missing_fields": missing_fields}), 400

    post_card(build_audit_card(data))
    safe_write_memory_step("contract_confirm", "success", f"Confirmed details for {ticket_id}", data)
    result = create_contract_after_confirm(ticket_id, data)
    if result.get("status") == "success":
        status_code = 200
    elif result.get("status") == "validation_error":
        status_code = 400
    else:
        status_code = 500
    return jsonify(result), status_code


@app.post("/sku-webhook")
def sku_webhook():
    raw_body = request.get_data()
    token = os.getenv("TEAMS_SKU_BOT_TOKEN", "")
    if not validate_hmac(raw_body, request.headers.get("Authorization", ""), token):
        return jsonify({"type": "message", "text": "HMAC validation failed."})

    body = request.get_json(force=True, silent=True) or {}
    message_text = extract_message_text(body)
    match = CONTRACT_PATTERN.search(message_text)
    if not match:
        return jsonify({"type": "message",
                        "text": "Please send a contract number like: @addskubot 00174876"})

    contract_number = match.group(1)

    def _bg():
        with app.app_context():
            result = _post_sku_confirmation_card(contract_number)
            if result.get("status") != "success":
                app.logger.info(
                    "[hrc-sku] %s: selection card was not posted; status=%s detail=%s",
                    contract_number,
                    result.get("status"),
                    result.get("detail"),
                )

    threading.Thread(target=_bg, daemon=True).start()

    return jsonify({
        "type": "message",
        "text": (
            f"Preparing SKU card for contract {contract_number}. "
            "I will post the SKU selection card to this channel shortly."
        ),
    })


@app.post("/sku-confirm")
def sku_confirm():
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    contract_number = (data.get("contract_number") or "").strip()
    if not contract_number:
        return jsonify({"status": "error", "detail": "missing contract_number"}), 400

    line_data = {
        "division":                data.get("division", ""),
        "product_name":            data.get("product_name", ""),
        "customer_order_category": data.get("customer_order_category", ""),
        "sku_description":         data.get("sku_description", ""),
        "eq_specif_grp":           data.get("eq_specif_grp", ""),
        "eq_specifi":              data.get("eq_specifi", ""),
        "eq_sub_grade":            data.get("eq_sub_grade", ""),
        "end_appn":                data.get("end_appn", ""),
        "order_qty":               data.get("order_qty", ""),
        "cust_req_date":           data.get("cust_req_date", ""),
        "width":                   data.get("width", ""),
        "thickness":               data.get("thickness", ""),
        "edge_con":                data.get("edge_con", ""),
        "plant_code":              data.get("plant_code", ""),
    }

    _run_sku_creation(contract_number, line_data)
    return jsonify({"status": "success", "contract_number": contract_number})


@app.post("/sku-select-confirm")
def sku_select_confirm():
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    contract_number = (data.get("contract_number") or "").strip()
    material = (data.get("material") or "").strip()
    description = (data.get("description") or data.get("sku_description") or "").strip()
    qty = (data.get("qty") or data.get("order_qty") or "").strip()

    missing = []
    if not contract_number:
        missing.append("Contract Number")
    if is_blank_card_value(material):
        missing.append("Material")
    if is_blank_card_value(description):
        missing.append("SKU / Description")
    if is_blank_card_value(qty):
        missing.append("Qty")
    if missing:
        message = f"Please fill {', '.join(missing)} before confirming"
        app.logger.info("[hrc-sku] validation failed for %s: %s", contract_number, ", ".join(missing))
        post_sku_card(build_hrc_sku_validation_failed_card(message, contract_number))
        return jsonify({"status": "validation_error", "missing_fields": missing}), 400

    context = _context_from_memory_or_payload(contract_number, data)
    selection = {"material": material, "description": description, "qty": qty}
    app.logger.info(
        "[hrc-sku] %s: selected material=%s description=%s qty=%s",
        contract_number,
        material,
        description,
        qty,
    )

    try:
        lookup = get_sku_details(
            "HRC",
            context.get("sold_to_party", ""),
            context.get("ship_to_party", ""),
            context.get("ship_plant_code", ""),
            material,
            description,
        )
        rows = lookup.get("rows") or []
        request_id = save_sku_pending_request(
            {"contract_number": contract_number, "context": context, "selection": selection, "rows": rows}
        )
        if len(rows) > 1:
            post_sku_card(build_hrc_sku_row_choice_card(context, selection, rows, request_id))
            return jsonify({"status": "row_choice_required", "request_id": request_id, "rows": len(rows)})

        details = _details_from_row(rows[0], material) if rows else _manual_hrc_details(selection)
        post_sku_card(build_hrc_sku_details_card(context, selection, details, request_id))
        return jsonify({"status": "details_card_posted", "request_id": request_id, "rows": len(rows)})
    except Exception as exc:
        app.logger.exception("[hrc-sku] detail lookup failed for %s: %s", contract_number, exc)
        post_sku_card(build_hrc_sku_validation_failed_card("Could not fetch HRC SKU details. Detailed error is available in Cloud Run logs", contract_number))
        return jsonify({"status": "error", "detail": str(exc)}), 500


@app.post("/sku-row-confirm")
def sku_row_confirm():
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    request_id = (data.get("request_id") or "").strip()
    row_index_raw = (data.get("row_index") or "").strip()
    pending = get_sku_pending_request(request_id) if request_id else None
    if not pending:
        return jsonify({"status": "error", "detail": "pending SKU request not found"}), 404
    try:
        row_index = int(row_index_raw)
        row = pending.get("rows", [])[row_index]
    except Exception:
        post_sku_card(build_hrc_sku_validation_failed_card("Please select one matching row", pending.get("contract_number", "")))
        return jsonify({"status": "validation_error", "detail": "invalid row_index"}), 400

    context = pending.get("context", {})
    selection = pending.get("selection", {})
    details = _details_from_row(row, selection.get("material", ""))
    post_sku_card(build_hrc_sku_details_card(context, selection, details, request_id))
    return jsonify({"status": "details_card_posted", "request_id": request_id, "row_index": row_index})


@app.post("/sku-details-confirm")
def sku_details_confirm():
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    contract_number = (data.get("contract_number") or "").strip()
    if not contract_number:
        return jsonify({"status": "error", "detail": "missing contract_number"}), 400

    material = (data.get("material") or "").strip()
    description = (data.get("description") or "").strip()
    qty = (data.get("qty") or "").strip()
    missing = []
    for label, key in [("Material", material), ("SKU / Description", description), ("Qty", qty)]:
        if is_blank_card_value(key):
            missing.append(label)
    if missing:
        post_sku_card(build_hrc_sku_validation_failed_card(f"Please fill {', '.join(missing)} before confirming SKU details", contract_number))
        return jsonify({"status": "validation_error", "missing_fields": missing}), 400

    details = dict(data)
    store_confirmed_hrc_sku(contract_number, details)
    safe_write_memory_step(
        "hrc_sku_details_confirmed",
        "success",
        f"Confirmed HRC SKU details for contract {contract_number}",
        {"contract_number": contract_number, "details": details},
    )
    post_sku_card(build_hrc_sku_confirmed_card(contract_number, details))
    return jsonify({"status": "success", "contract_number": contract_number})


def _post_sku_confirmation_card(contract_number: str) -> dict:
    try:
        app.logger.info("[hrc-sku] Loading contract context for %s", contract_number)
        context = find_contract_context(contract_number)
        if not context:
            post_sku_card(build_hrc_sku_validation_failed_card("Could not find this contract in Contract Logging memory", contract_number))
            return {"status": "not_found", "detail": "contract not found in memory"}

        division = (context.get("division") or "").strip().upper()
        if division != "HRC":
            post_sku_card(build_hrc_sku_validation_failed_card("Only HRC SKU confirmation is enabled for now", contract_number))
            return {"status": "unsupported_division", "detail": f"division={division or '<blank>'}"}

        if not context.get("sold_to_party") or not context.get("ship_to_party"):
            post_sku_card(build_hrc_sku_validation_failed_card("Could not find Sold To / Ship To party codes in memory", contract_number))
            return {"status": "missing_party_codes", "detail": "sold_to_party or ship_to_party missing"}

        context = _enrich_context_from_jira(context)
        lookup = get_sku_choices(
            "HRC",
            context.get("sold_to_party", ""),
            context.get("ship_to_party", ""),
            context.get("ship_plant_code", ""),
        )
        card = build_hrc_sku_selection_card(context, lookup)
        post_sku_card(card)
        safe_write_memory_step(
            "post_hrc_sku_selection_card",
            "success",
            f"Posted HRC SKU selection card for contract {contract_number}",
            {"contract_number": contract_number, "context": context},
        )
        return {"status": "success", "detail": "sku selection card posted"}
    except Exception as exc:
        app.logger.exception("[sku] Failed to post SKU card for %s: %s", contract_number, exc)
        try:
            post_sku_card(build_hrc_sku_validation_failed_card("Could not post HRC SKU card. Detailed error is available in Cloud Run logs", contract_number))
        except Exception:
            pass
        return {"status": "error", "detail": str(exc)}


def _run_sku_creation(contract_number: str, line_data: dict) -> None:
    try:
        from salesforce_add_contract_line import salesforce_add_contract_line

        app.logger.info("[sku] Starting line item creation for contract %s", contract_number)
        line_name = salesforce_add_contract_line(contract_number, line_data)
        if not line_name:
            raise RuntimeError("Contract line name was not captured after Save")
        app.logger.info("[sku] Line created: %s", line_name)
        post_sku_card(build_sku_success_card(contract_number, line_name))
        safe_write_memory_step(
            "create_sku_line",
            "success",
            f"Created SKU line {line_name} for contract {contract_number}",
            {"contract_number": contract_number, "line_name": line_name, "input": line_data},
        )
        record_contract_success(contract_number, line_data, line_name)
    except Exception as exc:
        app.logger.exception("[sku] Failed for contract %s: %s", contract_number, exc)
        try:
            post_sku_card(build_sku_failure_card(contract_number, str(exc)))
        except Exception as notify_exc:
            app.logger.exception("[sku] Could not post failure card: %s", notify_exc)
        record_contract_error(contract_number, line_data, str(exc))


def _context_from_memory_or_payload(contract_number: str, data: dict) -> dict:
    context = find_contract_context(contract_number) or {"contract_number": contract_number}
    fallback_keys = {
        "ticket_id": "ticket_id",
        "division": "division",
        "sold_to_party": "bp_code",
        "ship_to_party": "sp_code",
        "ship_plant_code": "ship_plant_code",
    }
    for target, source in fallback_keys.items():
        if not context.get(target) and data.get(source):
            context[target] = str(data.get(source)).strip()
    context.setdefault("contract_number", contract_number)
    context.setdefault("division", "HRC")
    return context


def _enrich_context_from_jira(context: dict) -> dict:
    if context.get("ship_plant_code"):
        return context
    ticket_id = (context.get("ticket_id") or "").strip()
    if not ticket_id:
        return context
    try:
        ticket = fetch_jira_ticket(ticket_id)
        if not ticket:
            return context
        details = prepare_contract_details(ticket)
        for key in ("ship_plant_code", "sold_to_party", "ship_to_party", "division"):
            if not context.get(key) and details.get(key):
                context[key] = str(details.get(key)).strip()
    except Exception as exc:
        app.logger.warning("[hrc-sku] Could not enrich context from Jira for %s: %s", ticket_id, exc)
    return context


def _manual_hrc_details(selection: dict) -> dict:
    return {
        "customer_order_category": "",
        "eq_specif_grp": "",
        "eq_specifi": "",
        "eq_sub_grade": "",
        "end_appn": "",
        "rh_req": "N",
        "plant_code": "",
        "cust_req_date": (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%d-%b-%Y"),
        "width": "",
        "thickness": "",
        "length": "",
        "edge_con": "",
        "material": selection.get("material", ""),
        "description": selection.get("description", ""),
        "qty": selection.get("qty", ""),
    }


def _details_from_row(row: dict, material: str) -> dict:
    details = _manual_hrc_details({"material": material})
    details.update(
        {
            "customer_order_category": _row_value(row, "CUST ORDER", "customer_order_category", "Cust.Grp", "Cust Grp"),
            "eq_specif_grp": _row_value(row, "EqSpecifGrp", "EQ SPECIF GRP", "eq_specif_grp"),
            "eq_specifi": _row_value(row, "EqSpecifi", "EQ SPECIFI", "eq_specifi"),
            "eq_sub_grade": _row_value(row, "EqSub_Grade", "EQ SUB GRADE", "eq_sub_grade"),
            "end_appn": _row_value(row, "END_APPN", "END APPN", "end_appn"),
            "rh_req": _row_value(row, "RH REQ", "rh_req") or "N",
            "plant_code": _row_value(row, "SHIP PLANT", "ship_plant", "ship_plant_code", "plant_code", "Plant Code"),
            "cust_req_date": _row_value(row, "Customer Requested Date", "CUST REQ DATE", "cust_req_date")
            or details["cust_req_date"],
            "width": _row_value(row, "WIDTH", "width"),
            "thickness": _row_value(row, "THICKNESS", "thickness"),
            "length": _row_value(row, "LENGTH", "length"),
            "edge_con": _row_value(row, "EDGE_CON", "EDGE CON", "edge_con"),
        }
    )
    return details


def _row_value(row: dict, *keys: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
        value = lowered.get(key.strip().lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def process_ticket(ticket_id: str) -> dict:
    try:
        ticket = fetch_jira_ticket(ticket_id)
        if ticket is None:
            post_text(f"Ticket {ticket_id} was not found in Jira.")
            safe_write_memory_step("fetch_jira_ticket", "failed", "Ticket not found", {"ticket_id": ticket_id})
            return {"status": "not_found", "ticket_id": ticket_id}

        details = prepare_contract_details(ticket)
        card = build_confirmation_card(details)
        post_card(card)
        safe_write_memory_step(
            "post_confirmation_card",
            "success",
            f"Posted confirmation card for {ticket_id}",
            {"ticket_id": ticket_id, "details": details},
        )
        return {"status": "success", "ticket_id": ticket_id}

    except (JiraAuthError, JiraConnectionError) as exc:
        handle_error("process_ticket", "JIRA_ERROR", str(exc), {"ticket_id": ticket_id})
        try:
            post_text(f"Could not fetch Jira ticket {ticket_id}: {exc}")
        except Exception as notify_exc:
            app.logger.exception("Could not post Jira error to Teams for %s: %s", ticket_id, notify_exc)
        return {"status": "error", "ticket_id": ticket_id, "detail": str(exc)}
    except Exception as exc:
        handle_error("process_ticket", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        try:
            post_text(f"Unexpected error while processing {ticket_id}: {exc}")
        except Exception as notify_exc:
            app.logger.exception("Could not post process_ticket error to Teams for %s: %s", ticket_id, notify_exc)
        return {"status": "error", "ticket_id": ticket_id, "detail": str(exc)}


def navigate_after_confirm(ticket_id: str) -> None:
    try:
        result = navigate_to_contract_page()
        post_card(build_navigation_success_card(ticket_id, result["url"]))
        safe_write_memory_step(
            "navigate_contract_page",
            "success",
            f"Successfully navigated to Contract page for {ticket_id}",
            {"ticket_id": ticket_id, "url": result["url"]},
        )
    except Exception as exc:
        handle_error("navigate_contract_page", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        post_text(f"Could not navigate to Contract page for {ticket_id}: {exc}")


def create_contract_after_confirm(ticket_id: str, data: dict) -> dict:
    missing_fields = validate_confirmed_contract_details(data)
    if missing_fields:
        app.logger.info("Contract creation blocked for %s; missing fields: %s", ticket_id, ", ".join(missing_fields))
        try:
            post_card(build_contract_validation_failed_card(ticket_id, missing_fields))
        except Exception as notify_exc:
            app.logger.exception("Could not post contract validation card: %s", notify_exc)
        safe_write_memory_step(
            "create_contract_validation",
            "failed",
            f"Blocked contract creation for {ticket_id}; missing required fields: {', '.join(missing_fields)}",
            {"ticket_id": ticket_id, "missing_fields": missing_fields, "input": data},
        )
        return {"status": "validation_error", "ticket_id": ticket_id, "missing_fields": missing_fields}

    past_errors = check_past_errors(ticket_id, data)
    if past_errors:
        app.logger.warning(
            "[self-learning] %d unresolved prior error(s) for contract_type=%s "
            "distribution_channel=%s — last: %s",
            len(past_errors),
            data.get("contract_type"),
            data.get("distribution_channel"),
            past_errors[-1].get("error_message", "")[:200],
        )

    try:
        app.logger.info("Starting JSW Steel Salesforce contract creation for %s", ticket_id)
        contract_number = create_contract_in_portal(data, ticket_id)
        if not contract_number:
            raise RuntimeError("Generated Contract Number was not captured after Save")
        app.logger.info("Created JSW Steel Salesforce contract %s for %s", contract_number, ticket_id)
        post_card(build_contract_created_card(ticket_id, contract_number))
        safe_write_memory_step(
            "create_contract_in_portal",
            "success",
            f"Created contract {contract_number} for {ticket_id} on JSW Steel Community SF portal",
            {"ticket_id": ticket_id, "contract_number": contract_number, "input": data},
        )
        record_contract_success(ticket_id, data, contract_number)
        return {"status": "success", "ticket_id": ticket_id, "contract_number": contract_number}
    except Exception as exc:
        app.logger.exception("Contract creation failed for %s: %s", ticket_id, exc)
        handle_error("create_contract_in_portal", type(exc).__name__, str(exc), {"ticket_id": ticket_id})
        record_contract_error(ticket_id, data, str(exc))
        try:
            post_card(build_contract_creation_failed_card(ticket_id, str(exc)))
        except Exception as notify_exc:
            app.logger.exception("Could not post contract creation failure card: %s", notify_exc)
        return {"status": "error", "ticket_id": ticket_id, "detail": str(exc)}


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


def normalise_confirm_payload(payload: dict) -> dict:
    """Accept direct card fields or common Power Automate response wrappers."""
    candidates = [
        payload,
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
        payload.get("body") if isinstance(payload.get("body"), dict) else None,
        payload.get("response") if isinstance(payload.get("response"), dict) else None,
    ]
    body = payload.get("body")
    if isinstance(body, dict):
        candidates.extend(
            [
                body.get("data") if isinstance(body.get("data"), dict) else None,
                body.get("response") if isinstance(body.get("response"), dict) else None,
            ]
        )
    response = payload.get("response")
    if isinstance(response, dict):
        candidates.append(response.get("data") if isinstance(response.get("data"), dict) else None)

    for candidate in candidates:
        if isinstance(candidate, dict) and (
            candidate.get("ticket_id")
            or candidate.get("contract_number")
            or candidate.get("request_id")
            or candidate.get("stage")
        ):
            return candidate
    return payload


def validate_confirmed_contract_details(data: dict) -> list[str]:
    missing = []
    required_fields = [("Distribution Channel", "distribution_channel")]
    for label, key in required_fields:
        if is_blank_card_value(data.get(key)):
            missing.append(label)
    return missing


def is_blank_card_value(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text in {"", "-", "•", "null", "None"}


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
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry) + "\n")
    except Exception:
        app.logger.exception("Could not write local error log")


def safe_write_memory_step(step: str, status: str, detail: str, extra: dict | None = None) -> None:
    try:
        write_memory_step(step, status, detail, extra)
    except Exception:
        app.logger.exception("Could not write local memory step")


def write_memory_step(step: str, status: str, detail: str, extra: dict | None = None) -> None:
    memory = read_memory()
    history = memory.setdefault("state", {}).setdefault("run_history", [])
    history.append({
        "step": step,
        "status": status,
        "detail": detail,
        "timestamp": utc_now(),
        "extra": extra or {},
    })
    memory["state"]["run_history"] = memory["state"]["run_history"][-200:]
    memory["last_run"] = utc_now()
    memory["last_action"] = detail
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")
    _write_gcs_memory(memory)


def read_memory() -> dict:
    if GCS_BUCKET:
        return _read_gcs_memory()
    if MEMORY_PATH.exists():
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    return dict(_MEMORY_DEFAULT)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    port = int(os.getenv("PORT") or os.getenv("FLASK_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
