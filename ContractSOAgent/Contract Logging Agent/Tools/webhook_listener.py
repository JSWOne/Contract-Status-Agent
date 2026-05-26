"""
Tool: webhook_listener.py
Purpose: Teams ContractBot webhook and Power Automate confirmation callback.
"""

import base64
import ast
import hashlib
import hmac
import json
import logging
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
    build_hrc_sku_line_created_card,
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
    store_confirmed_sku,
)
from create_contract_in_portal import create_contract_in_portal
from fetch_jira_ticket import JiraAuthError, JiraConnectionError, fetch_jira_ticket
from master_lookup import get_sku_choices, get_sku_details
from navigate_contract_page import navigate_to_contract_page
from notify_teams import post_card, post_text, post_sku_card


load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger().setLevel(LOG_LEVEL)
app.logger.setLevel(LOG_LEVEL)
logging.getLogger("salesforce_add_contract_line").setLevel(LOG_LEVEL)

TICKET_PATTERN = re.compile(r"\b(O360-\d+)\b", re.IGNORECASE)
CONTRACT_PATTERN = re.compile(r"\b(\d{7,9})\b")
BASE_DIR = Path(__file__).parent.parent
# /app is read-only in Cloud Run — use /tmp for local files
LOG_PATH = Path("/tmp/error.log") if os.environ.get("GCS_MEMORY_BUCKET") else BASE_DIR / "Logs" / "error.log"
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"

GCS_BUCKET = os.environ.get("GCS_MEMORY_BUCKET", "").strip()
GCS_MEMORY_BLOB = "contract-logging-agent/memory.json"

SUPPORTED_SKU_DIVISIONS = {"HRC", "CRCA", "GI", "GL"}

SALESFORCE_PRODUCT_BY_MATERIAL = {
    "HRC": {
        "S_HRCF": "HR Coil - (S_HRCF)",
        "S_HRCTLF": "HR Sheet & Plate - (S_HRCTLF)",
    },
    "CRCA": {
        "S_CRCACF": "CRCA Coil - (S_CRCACF)",
        "S_CRCASF": "CRCA Sheet - (S_CRCASF)",
    },
    "GI": {
        "S_GICF": "GI Coil - (S_GICF)",
        "S_GISF": "GI Sheet - (S_GISF)",
        "S_HRGICF": "HR GI Coil - (S_HRGICF)",
        "S_ZMCF": "ZM Coil - (S_ZMCF)",
    },
    "GL": {
        "S_GLCF": "Galvalume Coil - (S_GLCF)",
    },
}

PLANT_NAME_BY_CODE = {
    "1001": "1001 - Vijayanagar Works",
    "1014": "1014 - Tarapur Works",
    "1044": "1044 - JSCPL - DHAR",
}

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
                    "[sku] %s: selection card was not posted; status=%s detail=%s",
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
    if _is_hrc_details_payload(data):
        app.logger.info("[sku] Details payload received on /sku-select-confirm; routing to details handler")
        return _handle_sku_details_confirm_payload(data)

    contract_number = (data.get("contract_number") or "").strip()
    material = _normalise_material_value(data.get("material"))
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
        app.logger.info("[sku] validation failed for %s: %s", contract_number, ", ".join(missing))
        post_sku_card(build_hrc_sku_validation_failed_card(message, contract_number))
        return jsonify({"status": "validation_error", "missing_fields": missing}), 400

    context = _enrich_context_from_jira(_context_from_memory_or_payload(contract_number, data))
    division = (context.get("division") or data.get("division") or "").strip().upper()
    selection = {"material": material, "description": description, "qty": qty}
    app.logger.info(
        "[sku] %s: division=%s selected material=%s description=%s qty=%s",
        contract_number,
        division,
        material,
        description,
        qty,
    )

    try:
        lookup = get_sku_details(
            division,
            context.get("sold_to_party", ""),
            context.get("ship_to_party", ""),
            context.get("ship_plant_code", ""),
            material,
            description,
        )
        rows = lookup.get("rows") or []
        request_id = save_sku_pending_request(
            {"contract_number": contract_number, "division": division, "context": context, "selection": selection, "rows": rows}
        )
        if len(rows) > 1:
            app.logger.info(
                "[sku] %s: %s matching rows returned for %s; using the first row automatically",
                contract_number,
                len(rows),
                description,
            )

        details = _details_from_row(rows[0], material, context) if rows else _manual_hrc_details(selection, context)
        app.logger.info(
            "[sku] %s: details prefill snapshot=%s",
            contract_number,
            json.dumps(
                {
                    "customer_order_category": details.get("customer_order_category", ""),
                    "eq_specif_grp": details.get("eq_specif_grp", ""),
                    "eq_specifi": details.get("eq_specifi", ""),
                    "eq_sub_grade": details.get("eq_sub_grade", ""),
                    "end_appn": details.get("end_appn", ""),
                    "rh_req": details.get("rh_req", ""),
                    "plant_code": details.get("plant_code", ""),
                    "width": details.get("width", ""),
                    "thickness": details.get("thickness", ""),
                    "length": details.get("length", ""),
                    "thick_tol_type": details.get("thick_tol_type", ""),
                    "edge_con": details.get("edge_con", ""),
                    "oil_req": details.get("oil_req", ""),
                }
            ),
        )
        post_sku_card(build_hrc_sku_details_card(context, selection, details, request_id))
        return jsonify({"status": "details_card_posted", "request_id": request_id, "rows": len(rows)})
    except Exception as exc:
        app.logger.exception("[sku] detail lookup failed for %s: %s", contract_number, exc)
        post_sku_card(build_hrc_sku_validation_failed_card(f"Could not fetch {division or 'SKU'} details. Detailed error is available in Cloud Run logs", contract_number))
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
    context = _enrich_context_from_jira(context)
    details = _details_from_row(row, selection.get("material", ""), context)
    post_sku_card(build_hrc_sku_details_card(context, selection, details, request_id))
    return jsonify({"status": "details_card_posted", "request_id": request_id, "row_index": row_index})


@app.post("/sku-details-confirm")
def sku_details_confirm():
    data = normalise_confirm_payload(request.get_json(force=True, silent=True) or {})
    return _handle_sku_details_confirm_payload(data)


def _handle_sku_details_confirm_payload(data: dict):
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

    context = _enrich_context_from_jira(_context_from_memory_or_payload(contract_number, data))
    request_id = str(data.get("request_id") or "").strip()
    details = _backfill_sku_details_from_pending_row(dict(data), context, request_id)
    if request_id and _is_sku_request_duplicate(contract_number, request_id):
        app.logger.info("[sku] duplicate sku-details-confirm ignored: contract=%s request_id=%s", contract_number, request_id)
        safe_write_memory_step(
            "sku_details_confirmed",
            "success",
            f"Ignored duplicate SKU confirm callback for contract {contract_number}",
            {"contract_number": contract_number, "request_id": request_id},
        )
        return jsonify({"status": "duplicate_ignored", "contract_number": contract_number, "request_id": request_id})
    _mark_sku_request_status(contract_number, request_id, "in_progress")
    division = (context.get("division") or details.get("division") or "").strip().upper()
    store_confirmed_sku(contract_number, details, division)
    safe_write_memory_step(
        "sku_details_confirmed",
        "success",
        f"Confirmed {division or 'SKU'} details for contract {contract_number}",
        {"contract_number": contract_number, "division": division, "details": details},
    )
    post_sku_card(build_hrc_sku_confirmed_card(contract_number, details, context))

    line_data = _sku_details_to_salesforce_line_data(contract_number, details)

    def _bg():
        with app.app_context():
            _run_sku_creation(contract_number, line_data, details=details, hrc=True, request_id=request_id)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"status": "success", "contract_number": contract_number})


def _backfill_sku_details_from_pending_row(details: dict, context: dict, request_id: str) -> dict:
    """Teams can omit lower-card inputs; recover them from the saved master row."""
    if not request_id:
        return details
    pending = get_sku_pending_request(request_id)
    if not pending:
        return details

    rows = pending.get("rows") or []
    if not rows:
        return details

    target_material = (details.get("material") or pending.get("selection", {}).get("material") or "").strip()
    target_description = (details.get("description") or pending.get("selection", {}).get("description") or "").strip()
    row = _matching_master_row(rows, target_material, target_description) or rows[0]
    row_details = _details_from_row(row, target_material, context)

    backfilled = []
    for key, value in row_details.items():
        if is_blank_card_value(details.get(key)) and not is_blank_card_value(value):
            details[key] = value
            backfilled.append(key)
    if backfilled:
        app.logger.info(
            "[sku] %s: backfilled missing details from pending master row: %s",
            details.get("contract_number", ""),
            ", ".join(backfilled),
        )
    return details


def _matching_master_row(rows: list[dict], material: str, description: str) -> dict:
    material_norm = material.strip().upper()
    description_norm = description.strip().upper()
    for row in rows:
        row_material = _row_value(row, "MATERIAL", "material").strip().upper()
        row_description = _row_value(row, "DESCRIPTION", "description").strip().upper()
        if row_material == material_norm and row_description == description_norm:
            return row
    return {}


def _is_hrc_details_payload(data: dict) -> bool:
    stage = (data.get("stage") or "").strip().lower()
    if stage in {"hrc_sku_details", "crca_sku_details", "gi_sku_details", "gl_sku_details", "sku_details"}:
        return True
    detail_keys = {
        "customer_order_category",
        "eq_specif_grp",
        "eq_specifi",
        "eq_sub_grade",
        "end_appn",
        "rh_req",
        "cust_req_date",
        "width",
        "thickness",
        "length",
        "edge_con",
        "thick_tol_type",
        "oil_req",
        "s_brand",
        "spangle_type",
        "zinc_coating_min",
        "al_zn_coating_min",
        "sleeve_required",
    }
    return any(str(data.get(key) or "").strip() for key in detail_keys)


def _normalise_material_value(raw) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    # Normal case: already material code.
    if re.fullmatch(r"[A-Za-z0-9_]+", text):
        return text.upper()
    # Adaptive Card occasionally posts dict-like strings:
    # "{'material': 'S_GICF'}" or '{"material":"S_GICF"}'
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, dict):
            candidate = str(parsed.get("material") or parsed.get("value") or "").strip()
            if candidate:
                return candidate.upper()
    except Exception:
        pass
    # Fallback: extract first material-looking token like S_GICF
    match = re.search(r"\bS_[A-Z0-9_]+\b", text.upper())
    if match:
        return match.group(0)
    return text.upper()


def _post_sku_confirmation_card(contract_number: str) -> dict:
    try:
        app.logger.info("[sku] Loading contract context for %s", contract_number)
        context = find_contract_context(contract_number)
        if not context:
            post_sku_card(build_hrc_sku_validation_failed_card("Could not find this contract in Contract Logging memory", contract_number))
            return {"status": "not_found", "detail": "contract not found in memory"}

        division = (context.get("division") or "").strip().upper()
        if division not in SUPPORTED_SKU_DIVISIONS:
            post_sku_card(build_hrc_sku_validation_failed_card("Only HRC, CRCA, GI, and GL SKU confirmation are enabled for now", contract_number))
            return {"status": "unsupported_division", "detail": f"division={division or '<blank>'}"}

        if not context.get("sold_to_party") or not context.get("ship_to_party"):
            post_sku_card(build_hrc_sku_validation_failed_card("Could not find Sold To / Ship To party codes in memory", contract_number))
            return {"status": "missing_party_codes", "detail": "sold_to_party or ship_to_party missing"}

        context = _enrich_context_from_jira(context)
        lookup = get_sku_choices(
            division,
            context.get("sold_to_party", ""),
            context.get("ship_to_party", ""),
            context.get("ship_plant_code", ""),
        )
        app.logger.info(
            "[sku] %s lookup result: division=%s materials=%s skus=%s rows=%s",
            contract_number,
            division,
            len(lookup.get("materials") or []),
            len(lookup.get("skus") or []),
            len(lookup.get("rows") or []),
        )
        card = build_hrc_sku_selection_card(context, lookup)
        post_sku_card(card)
        safe_write_memory_step(
            "post_sku_selection_card",
            "success",
            f"Posted {division} SKU selection card for contract {contract_number}",
            {"contract_number": contract_number, "division": division, "context": context},
        )
        return {"status": "success", "detail": "sku selection card posted"}
    except Exception as exc:
        app.logger.exception("[sku] Failed to post SKU card for %s: %s", contract_number, exc)
        try:
            post_sku_card(build_hrc_sku_validation_failed_card("Could not post SKU card. Detailed error is available in Cloud Run logs", contract_number))
        except Exception:
            pass
        return {"status": "error", "detail": str(exc)}


def _run_sku_creation(
    contract_number: str,
    line_data: dict,
    details: dict | None = None,
    hrc: bool = False,
    request_id: str = "",
) -> None:
    try:
        from salesforce_add_contract_line import salesforce_add_contract_line

        app.logger.info("[sku] Starting line item creation for contract %s", contract_number)
        line_name = salesforce_add_contract_line(contract_number, line_data)
        if not line_name:
            raise RuntimeError("Contract line name was not captured after Save")
        app.logger.info("[sku] Line created: %s", line_name)
        if hrc:
            post_sku_card(build_hrc_sku_line_created_card(contract_number, line_name, details or line_data))
        else:
            post_sku_card(build_sku_success_card(contract_number, line_name))
        _remember_recent_sku_success(contract_number, line_data, line_name)
        safe_write_memory_step(
            "create_sku_line",
            "success",
            f"Created SKU line {line_name} for contract {contract_number}",
            {"contract_number": contract_number, "line_name": line_name, "input": line_data},
        )
        _mark_sku_request_status(contract_number, request_id, "success", line_name=line_name)
        record_contract_success(contract_number, line_data, line_name)
    except Exception as exc:
        duplicate_line = _extract_latest_line_from_no_new_error(str(exc))
        if duplicate_line and _is_recent_duplicate_success(contract_number, line_data, duplicate_line):
            app.logger.info(
                "[sku] Duplicate callback detected for contract %s; reusing line %s as success",
                contract_number,
                duplicate_line,
            )
            try:
                if hrc:
                    post_sku_card(build_hrc_sku_line_created_card(contract_number, duplicate_line, details or line_data))
                else:
                    post_sku_card(build_sku_success_card(contract_number, duplicate_line))
            except Exception as notify_exc:
                app.logger.exception("[sku] Could not post duplicate-success card: %s", notify_exc)
            safe_write_memory_step(
                "create_sku_line",
                "success",
                f"Reused recently created SKU line {duplicate_line} for duplicate callback on contract {contract_number}",
                {"contract_number": contract_number, "line_name": duplicate_line, "input": line_data},
            )
            _mark_sku_request_status(contract_number, request_id, "success", line_name=duplicate_line)
            return
        app.logger.exception("[sku] Failed for contract %s: %s", contract_number, exc)
        try:
            post_sku_card(build_sku_failure_card(contract_number, str(exc)))
        except Exception as notify_exc:
            app.logger.exception("[sku] Could not post failure card: %s", notify_exc)
        _mark_sku_request_status(contract_number, request_id, "failed", error=str(exc))
        record_contract_error(contract_number, line_data, str(exc))


def _hrc_details_to_salesforce_line_data(contract_number: str, details: dict) -> dict:
    return _sku_details_to_salesforce_line_data(contract_number, {**details, "division": "HRC"})


def _sku_details_to_salesforce_line_data(contract_number: str, details: dict) -> dict:
    context = _enrich_context_from_jira(find_contract_context(contract_number) or {"contract_number": contract_number})
    material = (details.get("material") or "").strip().upper()
    division = (details.get("division") or context.get("division") or "").strip().upper() or _division_from_material(material)
    plant_code = details.get("plant_code") or context.get("ship_plant_code", "")
    plant_code = _normalise_plant_for_salesforce(plant_code)
    customer_requested_date = _customer_requested_date_from_context(context) or details.get("cust_req_date", "")

    line_data = {
        "division": division,
        "product_name": SALESFORCE_PRODUCT_BY_MATERIAL.get(division, {}).get(material, details.get("product_name", "")),
        "customer_order_category": details.get("customer_order_category", ""),
        "sku_description": details.get("description", ""),
        "eq_specif_grp": details.get("eq_specif_grp", ""),
        "eq_specifi": details.get("eq_specifi", ""),
        "eq_sub_grade": details.get("eq_sub_grade", ""),
        "end_appn": details.get("end_appn", ""),
        "order_qty": details.get("qty", ""),
        "cust_req_date": _normalise_customer_requested_date(customer_requested_date, context.get("contract_end_date", "")),
        "width": details.get("width", ""),
        "thickness": details.get("thickness", ""),
        "length": details.get("length", ""),
        "edge_con": details.get("edge_con", ""),
        "thick_tol_type": details.get("thick_tol_type", ""),
        "oil_req": details.get("oil_req", ""),
        "s_brand": details.get("s_brand", ""),
        "spangle_type": details.get("spangle_type", ""),
        "zinc_coating_min": details.get("zinc_coating_min", ""),
        "al_zn_coating_min": details.get("al_zn_coating_min", ""),
        "sleeve_required": details.get("sleeve_required", ""),
        "plant_code": plant_code,
    }
    return line_data


def _division_from_material(material: str) -> str:
    material = (material or "").strip().upper()
    for division, products in SALESFORCE_PRODUCT_BY_MATERIAL.items():
        if material in products:
            return division
    return ""


def _normalise_plant_for_salesforce(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    if match:
        code = match.group(0)
        return PLANT_NAME_BY_CODE.get(code, text)
    return text


def _normalise_customer_requested_date(value: str, contract_end_date: str = "") -> str:
    requested = _parse_date(value)
    contract_end = _parse_date(contract_end_date)
    today = datetime.now(timezone.utc).date()
    if requested and requested.date() <= today:
        adjusted = datetime.combine(today + timedelta(days=1), datetime.min.time())
        app.logger.info(
            "[sku] Customer Requested Date %s is today/past; using next valid date %s",
            value,
            adjusted.strftime("%d/%m/%Y"),
        )
        requested = adjusted
    if requested and contract_end and requested > contract_end:
        app.logger.info(
            "[sku] Customer Requested Date %s is after Contract End Date %s; using contract end date",
            value,
            contract_end_date,
        )
        requested = contract_end
    if requested:
        return requested.strftime("%d/%m/%Y")
    return str(value or "").strip()


def _parse_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
        "%d %b %Y",
        "%d-%B-%Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _sku_signature(contract_number: str, line_data: dict) -> str:
    fields = [
        str(contract_number or "").strip(),
        str(line_data.get("division", "")).strip().upper(),
        str(line_data.get("product_name", "")).strip().upper(),
        str(line_data.get("sku_description", "")).strip().upper(),
        str(line_data.get("order_qty", "")).strip(),
        str(line_data.get("plant_code", "")).strip().upper(),
        str(line_data.get("cust_req_date", "")).strip(),
    ]
    return "|".join(fields)


def _remember_recent_sku_success(contract_number: str, line_data: dict, line_name: str) -> None:
    memory = _read_gcs_memory()
    recent = memory.setdefault("sku_recent_success", {})
    now = datetime.now(timezone.utc)
    signature = _sku_signature(contract_number, line_data)
    recent[signature] = {"timestamp": now.isoformat(), "line_name": line_name}
    cutoff = now - timedelta(hours=2)
    for key, value in list(recent.items()):
        ts = _parse_iso_dt(value.get("timestamp", ""))
        if not ts or ts < cutoff:
            recent.pop(key, None)
    _write_gcs_memory(memory)


def _is_recent_duplicate_success(contract_number: str, line_data: dict, duplicate_line: str) -> bool:
    memory = _read_gcs_memory()
    recent = memory.get("sku_recent_success", {})
    duplicate_line = str(duplicate_line or "").strip()
    if not duplicate_line:
        return False
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=20)

    # First preference: exact same signature.
    item = recent.get(_sku_signature(contract_number, line_data))
    if item and str(item.get("line_name", "")).strip() == duplicate_line:
        ts = _parse_iso_dt(item.get("timestamp", ""))
        if ts and ts >= cutoff:
            return True

    # Fallback: same contract + same line id in recent successes,
    # even if payload normalization differs between duplicate callbacks.
    contract_prefix = f"{str(contract_number or '').strip()}|"
    for signature, value in recent.items():
        if not str(signature).startswith(contract_prefix):
            continue
        if str(value.get("line_name", "")).strip() != duplicate_line:
            continue
        ts = _parse_iso_dt(value.get("timestamp", ""))
        if ts and ts >= cutoff:
            return True
    return False


def _extract_latest_line_from_no_new_error(message: str) -> str:
    text = str(message or "")
    if "No new Contract Line Item was created" not in text:
        return ""
    match = re.search(r"Latest line is still\s+(\d{7,9}_\d+)", text)
    return match.group(1) if match else ""


def _parse_iso_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _mark_sku_request_status(contract_number: str, request_id: str, status: str, line_name: str = "", error: str = "") -> None:
    if not request_id:
        return
    memory = _read_gcs_memory()
    recent = memory.setdefault("sku_confirm_requests", {})
    now = datetime.now(timezone.utc)
    key = f"{str(contract_number or '').strip()}|{request_id}"
    recent[key] = {
        "contract_number": str(contract_number or "").strip(),
        "request_id": request_id,
        "status": status,
        "line_name": str(line_name or "").strip(),
        "error": str(error or "").strip(),
        "timestamp": now.isoformat(),
    }
    cutoff = now - timedelta(hours=6)
    for k, v in list(recent.items()):
        ts = _parse_iso_dt(v.get("timestamp", ""))
        if not ts or ts < cutoff:
            recent.pop(k, None)
    _write_gcs_memory(memory)


def _is_sku_request_duplicate(contract_number: str, request_id: str) -> bool:
    if not request_id:
        return False
    memory = _read_gcs_memory()
    recent = memory.get("sku_confirm_requests", {})
    key = f"{str(contract_number or '').strip()}|{request_id}"
    item = recent.get(key)
    if not item:
        return False
    ts = _parse_iso_dt(item.get("timestamp", ""))
    if not ts:
        return False
    now = datetime.now(timezone.utc)
    if ts < now - timedelta(minutes=30):
        return False
    status = str(item.get("status", "")).strip()
    if status == "in_progress" and ts < now - timedelta(minutes=10):
        return False
    return status in {"in_progress", "success"}


def _context_from_memory_or_payload(contract_number: str, data: dict) -> dict:
    context = find_contract_context(contract_number) or {"contract_number": contract_number}
    fallback_keys = {
        "ticket_id": "ticket_id",
        "division": "division",
        "sold_to_party": "bp_code",
        "ship_to_party": "sp_code",
        "ship_plant_code": "ship_plant_code",
        "customer_requested_delivery_date": "customer_requested_delivery_date",
        "contract_end_date": "contract_end_date",
    }
    for target, source in fallback_keys.items():
        if not context.get(target) and data.get(source):
            context[target] = str(data.get(source)).strip()
    if not context.get("customer_requested_delivery_date") and data.get("cust_req_date"):
        context["customer_requested_delivery_date"] = str(data.get("cust_req_date")).strip()
    context.setdefault("contract_number", contract_number)
    if data.get("division") and not context.get("division"):
        context["division"] = str(data.get("division")).strip()
    return context


def _enrich_context_from_jira(context: dict) -> dict:
    needed_keys = (
        "ship_plant_code",
        "sold_to_party",
        "ship_to_party",
        "division",
        "customer_requested_delivery_date",
        "contract_end_date",
    )
    if all(context.get(key) for key in needed_keys):
        return context
    ticket_id = (context.get("ticket_id") or "").strip()
    if not ticket_id:
        return context
    try:
        ticket = fetch_jira_ticket(ticket_id)
        if not ticket:
            return context
        details = prepare_contract_details(ticket)
        for key in needed_keys:
            if not context.get(key) and details.get(key):
                context[key] = str(details.get(key)).strip()
    except Exception as exc:
        app.logger.warning("[sku] Could not enrich context from Jira for %s: %s", ticket_id, exc)
    return context


def _customer_requested_date_from_context(context: dict | None) -> str:
    context = context or {}
    value = (
        context.get("customer_requested_delivery_date")
        or context.get("cust_req_date")
        or context.get("Customer Requested Delivery Date")
        or context.get("Customer Requested Date")
    )
    normalised = _normalise_customer_requested_date(value or "", context.get("contract_end_date", ""))
    return normalised or datetime.now(timezone.utc).strftime("%d/%m/%Y")


def _manual_hrc_details(selection: dict, context: dict | None = None) -> dict:
    division = ((context or {}).get("division") or selection.get("division") or "").strip().upper()
    return {
        "customer_order_category": "",
        "eq_specif_grp": "",
        "eq_specifi": "",
        "eq_sub_grade": "",
        "end_appn": "",
        "rh_req": "N",
        "plant_code": (context or {}).get("ship_plant_code", ""),
        "cust_req_date": _customer_requested_date_from_context(context),
        "width": "",
        "thickness": "",
        "length": "",
        "edge_con": "",
        "thick_tol_type": "",
        "oil_req": "",
        "material": selection.get("material", ""),
        "description": selection.get("description", ""),
        "qty": selection.get("qty", ""),
        "division": division,
    }


def _details_from_row(row: dict, material: str, context: dict | None = None) -> dict:
    details = _manual_hrc_details({"material": material}, context)
    context_customer_requested_date = _customer_requested_date_from_context(context)
    details.update(
        {
            "customer_order_category": _row_value(row, "CUST ORDER", "customer_order_category", "Cust.Grp", "Cust Grp"),
            "eq_specif_grp": _row_value(row, "EqSpecifGrp", "EQ SPECIF GRP", "eq_specif_grp"),
            "eq_specifi": _row_value(row, "EqSpecifi", "EQ SPECIFI", "eq_specifi"),
            "eq_sub_grade": _row_value(row, "EqSub_Grade", "EQ SUB GRADE", "eq_sub_grade"),
            "end_appn": _row_value(row, "END_APPN", "END APPN", "end_appn"),
            "rh_req": _row_value(row, "RH REQ", "rh_req") or "N",
            "plant_code": _row_value(row, "SHIP PLANT", "ship_plant", "ship_plant_code", "plant_code", "Plant Code")
            or details["plant_code"],
            "cust_req_date": context_customer_requested_date
            or _row_value(row, "Customer Requested Date", "CUST REQ DATE", "cust_req_date")
            or details["cust_req_date"],
            "width": _row_value(row, "WIDTH", "width"),
            "thickness": _row_value(row, "THICKNESS", "thickness"),
            "length": _row_value(row, "LENGTH", "length"),
            "edge_con": _row_value(row, "EDGE_CON", "EDGE CON", "edge_con"),
            "thick_tol_type": _row_value(row, "THICK_TOL_TYPE", "Thickness Tolerance Type", "thick_tol_type"),
            "oil_req": _row_value(row, "OIL_REQ", "Oil Required", "oil_req"),
            "s_brand": _row_value(row, "BRAND", "S Brand", "s_brand"),
            "spangle_type": _row_value(row, "S_SPANGLE_TYPE", "Spangle Type", "spangle_type"),
            "zinc_coating_min": _row_value(row, "ZINC COATING", "ZINC_COAT", "Zin_Coating Min(GSM)", "zinc_coating_min"),
            "al_zn_coating_min": _row_value(row, "AL ZN COATING MIN", "AL_ZN_COATING_MIN", "AL ZN Coating GSM MIN", "al_zn_coating_min"),
            "sleeve_required": _row_value(row, "SO_SLEEVE_REQD", "Sleeve Required?", "Sleeve Required", "sleeve_required"),
        }
    )
    return details


def _row_value(row: dict, *keys: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    canonical = {_canonical_row_key(k): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
        value = lowered.get(key.strip().lower())
        if value not in (None, ""):
            return str(value).strip()
        value = canonical.get(_canonical_row_key(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _canonical_row_key(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"_x([0-9a-f]{4})_", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"[^a-z0-9]", "", text)


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
    """Accept direct card fields or common Power Automate response wrappers.

    Some PA payloads include ticket_id at top-level but edited card fields under
    body/data/response. Return a merged canonical dict so required values are not lost.
    """
    if not isinstance(payload, dict):
        return {}

    candidates = []

    def _add(obj):
        if isinstance(obj, dict):
            candidates.append(obj)

    _add(payload)
    _add(payload.get("data"))
    _add(payload.get("body"))
    _add(payload.get("response"))

    body = payload.get("body")
    if isinstance(body, dict):
        _add(body.get("data"))
        _add(body.get("response"))

    response = payload.get("response")
    if isinstance(response, dict):
        _add(response.get("data"))

    key_aliases = {
        "ticket_id": ["ticket_id", "ticket id", "ticketid"],
        "contract_number": ["contract_number", "contract number", "contractnumber"],
        "contract_type": ["contract_type", "contract type", "contracttype"],
        "contract_source": ["contract_source", "contract source", "contractsource"],
        "sold_to_party": ["sold_to_party", "sold to party", "soldtoparty"],
        "ship_to_party": ["ship_to_party", "ship to party", "shiptoparty"],
        "ship_plant_code": ["ship_plant_code", "ship plant code", "shipplantcode"],
        "payer": ["payer"],
        "division": ["division"],
        "distribution_channel": ["distribution_channel", "distribution channel", "distributionchannel"],
        "po_number": ["po_number", "po number", "ponumber"],
        "po_date": ["po_date", "po date", "podate"],
        "contract_end_date": ["contract_end_date", "contract end date", "contractenddate"],
        "request_id": ["request_id", "request id", "requestid"],
        "stage": ["stage"],
    }

    def _canon(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

    merged = {}
    # Prefer later wrappers (usually deeper PA body/data payloads) over top-level.
    for candidate in candidates:
        lowered = {_canon(k): v for k, v in candidate.items()}
        for target, aliases in key_aliases.items():
            for alias in aliases:
                value = lowered.get(_canon(alias))
                if value is not None and str(value).strip() != "":
                    merged[target] = value
                    break

        # Keep existing passthrough fields used by SKU routes.
        for key in (
            "material",
            "description",
            "sku_description",
            "qty",
            "order_qty",
            "customer_order_category",
            "eq_specif_grp",
            "eq_specifi",
            "eq_sub_grade",
            "end_appn",
            "rh_req",
            "cust_req_date",
            "width",
            "thickness",
            "length",
            "edge_con",
            "thick_tol_type",
            "oil_req",
            "s_brand",
            "spangle_type",
            "zinc_coating_min",
            "plant_code",
        ):
            value = candidate.get(key)
            if value is not None and str(value).strip() != "":
                merged[key] = value

    if merged:
        return merged
    return payload


def validate_confirmed_contract_details(data: dict) -> list[str]:
    missing = []
    required_fields = [
        ("Contract Type", "contract_type"),
        ("Distribution Channel", "distribution_channel"),
    ]
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
