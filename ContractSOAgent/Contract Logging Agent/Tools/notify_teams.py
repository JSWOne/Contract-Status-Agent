"""
Tool: notify_teams.py
Purpose: Post text and Adaptive Card payloads to the Contract logging Teams channel.
"""

import os
import time
import logging
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))
log = logging.getLogger(__name__)


def post_to_contract_log(payload: dict, target: str = "main") -> bool:
    target = (target or "main").strip().lower()
    env_name = "TEAMS_CONTRACT_LOG_TEST_WEBHOOK_URL" if target in {"test", "testing"} else "TEAMS_CONTRACT_LOG_WEBHOOK_URL"
    webhook_url = os.environ.get(env_name, "").strip()
    if not webhook_url:
        raise RuntimeError(f"{env_name} is not set")

    last_exc = None
    for attempt in range(1, 5):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=(10, 60),
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            log.info("Posted Contract Logging Teams payload on attempt %s", attempt)
            return True
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("Teams/Power Automate post failed on attempt %s/4: %s", attempt, exc)
            if attempt < 4:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Could not post to Teams/Power Automate after retries: {last_exc}") from last_exc


def post_text(text: str, target: str = "main") -> bool:
    return post_to_contract_log({"text": text}, target=target)


def post_card(card: dict, target: str = "main") -> bool:
    return post_to_contract_log({"adaptive_card": card}, target=target)


def post_to_sku_log(payload: dict) -> bool:
    webhook_url = os.environ.get("TEAMS_SKU_LOG_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("TEAMS_SKU_LOG_WEBHOOK_URL is not set")

    last_exc = None
    for attempt in range(1, 5):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=(10, 60),
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            response_preview = (response.text or "").strip().replace("\n", " ")[:300]
            log.info(
                "Posted SKU Teams payload on attempt %s status=%s response=%s",
                attempt,
                response.status_code,
                response_preview or "<empty>",
            )
            return True
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("SKU Teams/Power Automate post failed on attempt %s/4: %s", attempt, exc)
            if attempt < 4:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Could not post to SKU Teams/Power Automate after retries: {last_exc}") from last_exc


def post_sku_card(card: dict) -> bool:
    return post_to_sku_log({"adaptive_card": card})
