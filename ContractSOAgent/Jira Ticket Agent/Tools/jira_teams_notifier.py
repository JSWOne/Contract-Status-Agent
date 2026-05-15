"""
Tool Name   : jira_teams_notifier.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : Build and post new Jira ticket Teams cards through Power Automate.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from jira_client import write_error_log


load_dotenv(Path(__file__).with_name(".env"))


def notify_jira_ticket_created(payload: dict[str, Any]) -> dict[str, Any]:
    ticket = normalize_jira_created_payload(payload)
    card = payload.get("adaptive_card")
    if not isinstance(card, dict):
        card = build_jira_created_card(ticket)

    webhook_url = os.getenv("JIRA_TEAMS_WEBHOOK_URL", "").strip()
    if not webhook_url:
        message = "JIRA_TEAMS_WEBHOOK_URL is not configured on Jira Ticket Agent."
        write_error_log(
            tool="jira_teams_notifier.py",
            error_code="TEAMS_CONFIG_MISSING",
            error_message=message,
            input_payload={"ticket": ticket},
            ticket_id=ticket.get("key"),
        )
        return {
            "ok": False,
            "teams_posted": False,
            "ticket": ticket,
            "error": message,
        }

    request_payload = {
        "adaptive_card": card,
        "adaptive_card_json": json.dumps(card),
        "ticket": ticket,
    }

    last_error = None
    for attempt in range(1, 5):
        try:
            response = requests.post(
                webhook_url,
                json=request_payload,
                timeout=(10, 60),
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            return {
                "ok": True,
                "teams_posted": True,
                "ticket": ticket,
                "status_code": response.status_code,
            }
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(2 * attempt)

    message = f"Could not post Jira ticket card to Teams: {last_error}"
    write_error_log(
        tool="jira_teams_notifier.py",
        error_code="TEAMS_POST_FAILED",
        error_message=message,
        input_payload={"ticket": ticket},
        ticket_id=ticket.get("key"),
    )
    return {
        "ok": False,
        "teams_posted": False,
        "ticket": ticket,
        "error": message,
    }


def normalize_jira_created_payload(payload: dict[str, Any]) -> dict[str, str]:
    issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}

    key = _first(
        payload.get("key"),
        payload.get("issueKey"),
        issue.get("key"),
        payload.get("ticket_id"),
        payload.get("ticketId"),
    )
    summary = _first(payload.get("summary"), fields.get("summary"), payload.get("title"), "-")
    reporter = _extract_value(_first(payload.get("reporter"), fields.get("reporter"), "-"))

    return {
        "key": str(key or "").strip(),
        "summary": str(summary or "").strip(),
        "order_business_unit": _field(payload, fields, "Order Business unit"),
        "request_to": _field(payload, fields, "Request to"),
        "order_type": _field(payload, fields, "Order Type"),
        "plant_name": _field(payload, fields, "Plant Name"),
        "product_type": _field(payload, fields, "Product Type"),
        "slo_id": _field(payload, fields, "SLO ID", "Opportunity ID"),
        "delivery_type": _field(payload, fields, "Delivery type"),
        "reporter": reporter,
        "url": _first(
            payload.get("url"),
            payload.get("ticket_url"),
            payload.get("self"),
            f"https://{os.getenv('JIRA_DOMAIN', 'jswone.atlassian.net')}/browse/{key}" if key else "",
        ),
    }


def build_jira_created_card(ticket: dict[str, str]) -> dict[str, Any]:
    facts = [
        ("Order Business unit", ticket.get("order_business_unit")),
        ("Request to", ticket.get("request_to")),
        ("Order Type", ticket.get("order_type")),
        ("Plant Name", ticket.get("plant_name")),
        ("Product Type", ticket.get("product_type")),
        ("SLO ID", ticket.get("slo_id")),
        ("Delivery type", ticket.get("delivery_type")),
        ("Reporter", ticket.get("reporter")),
    ]
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": "New Jira Ticket Created",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": f"**{ticket.get('key') or '-'}** — {ticket.get('summary') or '-'}",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": title, "value": value or "-"}
                    for title, value in facts
                    if value not in (None, "")
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "View Full Ticket Details",
                "url": ticket.get("url") or f"https://{os.getenv('JIRA_DOMAIN', 'jswone.atlassian.net')}",
            }
        ],
    }


def _field(payload: dict[str, Any], fields: dict[str, Any], *names: str) -> str:
    for name in names:
        for candidate in (
            payload.get(name),
            payload.get(_snake(name)),
            payload.get(_camel(name)),
            fields.get(name),
        ):
            value = _extract_value(candidate)
            if value:
                return value
    return ""


def _extract_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "key"):
            if value.get(key) is not None:
                return str(value[key]).strip()
    if isinstance(value, list):
        return ", ".join(part for part in (_extract_value(item) for item in value) if part)
    return str(value).strip()


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def _snake(value: str) -> str:
    return value.lower().replace("/", " ").replace("-", " ").replace(" ", "_")


def _camel(value: str) -> str:
    parts = _snake(value).split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])
