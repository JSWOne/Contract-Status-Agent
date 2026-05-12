"""
Power Automate-backed HRC master lookup helper.

The Cloud Run service does not read the SharePoint Excel master directly. It
calls a small Power Automate helper flow that owns Excel/SharePoint access and
returns filtered material/SKU data.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))


def normalise_party_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return digits.zfill(10)


def get_sku_choices(division: str, bp_code: str, sp_code: str) -> dict[str, Any]:
    return _call_lookup(
        {
            "action": "get_sku_choices",
            "division": division,
            "bp_code": normalise_party_code(bp_code),
            "sp_code": normalise_party_code(sp_code),
        }
    )


def get_sku_details(
    division: str,
    bp_code: str,
    sp_code: str,
    material: str,
    description: str,
) -> dict[str, Any]:
    return _call_lookup(
        {
            "action": "get_sku_details",
            "division": division,
            "bp_code": normalise_party_code(bp_code),
            "sp_code": normalise_party_code(sp_code),
            "material": (material or "").strip(),
            "description": (description or "").strip(),
        }
    )


def _call_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    url = os.getenv("HRC_MASTER_LOOKUP_URL", "").strip()
    if not url:
        raise RuntimeError("HRC_MASTER_LOOKUP_URL is not configured.")

    response = requests.post(url, json=payload, timeout=90)
    response.raise_for_status()
    if not (response.text or "").strip():
        return {"status": "success", "materials": [], "skus": [], "rows": []}

    data = response.json()
    if str(data.get("status", "success")).lower() not in {"success", "ok"}:
        raise RuntimeError(data.get("message") or data.get("error") or "HRC master lookup failed.")
    return data
