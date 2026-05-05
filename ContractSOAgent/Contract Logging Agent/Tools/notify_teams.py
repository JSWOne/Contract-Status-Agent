"""
Tool: notify_teams.py
Purpose: Post text and Adaptive Card payloads to the Contract logging Teams channel.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))


def post_to_contract_log(payload: dict) -> bool:
    webhook_url = os.environ.get("TEAMS_CONTRACT_LOG_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("TEAMS_CONTRACT_LOG_WEBHOOK_URL is not set")
    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
    return True


def post_text(text: str) -> bool:
    return post_to_contract_log({"text": text})


def post_card(card: dict) -> bool:
    return post_to_contract_log({"adaptive_card": card})
