"""
Shared memory helpers for the Contract Logging Agent.

This module is intentionally read/write focused and does not import the Flask
webhook module, so SKU flows can read contract context without touching the
existing contract creation routes.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).parent.parent
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"

load_dotenv(Path(__file__).with_name(".env"))

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gcs_client():
    try:
        from google.cloud import storage

        return storage.Client()
    except Exception:
        return None


def read_memory() -> dict[str, Any]:
    if GCS_BUCKET:
        try:
            client = _gcs_client()
            if client:
                blob = client.bucket(GCS_BUCKET).blob(GCS_MEMORY_BLOB)
                if blob.exists():
                    return json.loads(blob.download_as_text())
        except Exception:
            pass
    if MEMORY_PATH.exists():
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    return dict(_MEMORY_DEFAULT)


def write_memory(memory: dict[str, Any]) -> None:
    memory["last_run"] = _utc_now()
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")
    if not GCS_BUCKET:
        return
    try:
        client = _gcs_client()
        if client:
            blob = client.bucket(GCS_BUCKET).blob(GCS_MEMORY_BLOB)
            blob.upload_from_string(json.dumps(memory, indent=2), content_type="application/json")
    except Exception:
        pass


def normalise_contract_number(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits


def normalise_party_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return digits.zfill(10)


def find_contract_context(contract_number: str) -> dict[str, str] | None:
    wanted = normalise_contract_number(contract_number)
    if not wanted:
        return None

    memory = read_memory()
    context: dict[str, str] = {"contract_number": wanted}

    for entry in memory.get("successes", []):
        if normalise_contract_number(entry.get("contract_number", "")) == wanted:
            _merge_contract_context(context, entry)

    for candidate in _walk_dicts(memory):
        if normalise_contract_number(candidate.get("contract_number", "")) != wanted:
            continue
        _merge_contract_context(context, candidate)
        if isinstance(candidate.get("input"), dict):
            _merge_contract_context(context, candidate["input"])
        if isinstance(candidate.get("extra"), dict):
            _merge_contract_context(context, candidate["extra"])
            if isinstance(candidate["extra"].get("input"), dict):
                _merge_contract_context(context, candidate["extra"]["input"])

    if len(context) == 1:
        return None

    context["sold_to_party"] = normalise_party_code(context.get("sold_to_party", ""))
    context["ship_to_party"] = normalise_party_code(context.get("ship_to_party", ""))
    return context


def _merge_contract_context(target: dict[str, str], source: dict[str, Any]) -> None:
    aliases = {
        "ticket_id": ("ticket_id", "jira_ticket"),
        "division": ("division",),
        "sold_to_party": ("sold_to_party", "sold_to", "bp_code", "b_p_code"),
        "ship_to_party": ("ship_to_party", "ship_to", "sp_code", "s_p_code"),
        "ship_plant_code": ("ship_plant_code", "ship_plant", "plant_code", "SHIP PLANT", "Ship Plant Code", "Plant Name"),
        "payer": ("payer",),
        "distribution_channel": ("distribution_channel",),
        "contract_type": ("contract_type",),
        "contract_end_date": ("contract_end_date", "Contract End Date"),
    }
    for target_key, keys in aliases.items():
        if target.get(target_key):
            continue
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                target[target_key] = str(value).strip()
                break


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def save_sku_pending_request(payload: dict[str, Any], request_id: str | None = None) -> str:
    memory = read_memory()
    request_id = request_id or f"sku-{normalise_contract_number(payload.get('contract_number', ''))}-{int(time.time())}"
    pending = memory.setdefault("sku_pending_requests", {})
    pending[request_id] = {"timestamp": _utc_now(), **payload}
    if len(pending) > 100:
        for key in sorted(pending.keys())[:-100]:
            pending.pop(key, None)
    memory["last_action"] = f"Saved pending HRC SKU request {request_id}"
    write_memory(memory)
    return request_id


def get_sku_pending_request(request_id: str) -> dict[str, Any] | None:
    return read_memory().get("sku_pending_requests", {}).get(request_id)


def store_confirmed_hrc_sku(contract_number: str, payload: dict[str, Any]) -> None:
    memory = read_memory()
    confirmations = memory.setdefault("sku_confirmations", [])
    confirmations.append(
        {
            "timestamp": _utc_now(),
            "contract_number": normalise_contract_number(contract_number),
            "division": "HRC",
            "details": payload,
        }
    )
    memory["sku_confirmations"] = confirmations[-200:]
    memory["last_action"] = f"Confirmed HRC SKU details for contract {contract_number}"
    write_memory(memory)
