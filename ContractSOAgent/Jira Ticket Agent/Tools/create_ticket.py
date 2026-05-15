"""
Tool Name   : create_ticket.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : Create or deduplicate Jira tickets for agent failures and manual review items.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from jira_client import (
    JiraClient,
    JiraAgentError,
    load_memory,
    make_fingerprint,
    save_memory,
    utc_now,
    write_error_log,
)


def create_or_update_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    required = ["ticket_type", "priority", "summary", "description", "affected_skill"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    memory = load_memory()
    fingerprint = make_fingerprint(payload)
    pending_items = memory.setdefault("state", {}).setdefault("pending_items", [])

    existing = next(
        (
            item
            for item in pending_items
            if item.get("fingerprint") == fingerprint and item.get("status") != "Done"
        ),
        None,
    )

    client = JiraClient()
    if existing:
        comment = _build_repeat_comment(payload)
        client.add_comment(existing["ticket_id"], comment)
        existing["last_seen"] = utc_now()
        existing["repeat_count"] = int(existing.get("repeat_count", 1)) + 1
        save_memory(memory, f"updated existing Jira ticket {existing['ticket_id']}")
        return {
            "created": False,
            "ticket_id": existing["ticket_id"],
            "ticket_url": existing["ticket_url"],
            "fingerprint": fingerprint,
        }

    project_key = os.getenv("JIRA_PROJECT_KEY", "").strip()
    if not project_key:
        raise ValueError("Set JIRA_PROJECT_KEY before creating Jira tickets.")

    issue = client.create_issue(
        project_key=project_key,
        issue_type=payload["ticket_type"],
        summary=payload["summary"],
        description=_build_description(payload),
        priority=payload["priority"],
        labels=_labels(payload),
    )

    ticket_id = issue["key"]
    domain = os.getenv("JIRA_DOMAIN", "").strip().rstrip("/")
    base_url = domain if domain.startswith("http") else f"https://{domain}"
    ticket_url = f"{base_url}/browse/{ticket_id}"

    pending_items.append(
        {
            "fingerprint": fingerprint,
            "ticket_id": ticket_id,
            "ticket_url": ticket_url,
            "summary": payload["summary"],
            "priority": payload["priority"],
            "affected_skill": payload["affected_skill"],
            "affected_record_id": payload.get("affected_record_id"),
            "status": "Open",
            "created_at": utc_now(),
            "last_seen": utc_now(),
            "repeat_count": 1,
        }
    )
    memory["state"]["last_processed_id"] = ticket_id
    save_memory(memory, f"created Jira ticket {ticket_id}")

    return {
        "created": True,
        "ticket_id": ticket_id,
        "ticket_url": ticket_url,
        "fingerprint": fingerprint,
    }


def _build_description(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Affected Skill: {payload.get('affected_skill')}",
            f"Affected Record ID: {payload.get('affected_record_id') or 'N/A'}",
            f"Priority: {payload.get('priority')}",
            f"Error Code: {payload.get('error_code') or 'N/A'}",
            "",
            "Description:",
            str(payload.get("description") or ""),
            "",
            "Error Log Entry:",
            json.dumps(payload.get("error_log_entry") or {}, indent=2),
        ]
    )


def _build_repeat_comment(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "The same issue was detected again.",
            f"Detected At: {utc_now()}",
            f"Affected Record ID: {payload.get('affected_record_id') or 'N/A'}",
            "",
            str(payload.get("description") or ""),
        ]
    )


def _labels(payload: dict[str, Any]) -> list[str]:
    labels = ["contract-so-agent"]
    skill = str(payload.get("affected_skill", "")).lower().replace(" ", "-")
    if skill:
        labels.append(skill[:255])
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a Jira ticket.")
    parser.add_argument("--payload", help="JSON payload string")
    parser.add_argument("--payload-file", help="Path to JSON payload file")
    args = parser.parse_args()

    try:
        if args.payload_file:
            with open(args.payload_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        elif args.payload:
            payload = json.loads(args.payload)
        else:
            payload = json.load(sys.stdin)

        result = create_or_update_ticket(payload)
        print(json.dumps(result, indent=2))
        return 0
    except (JiraAgentError, ValueError, json.JSONDecodeError) as exc:
        write_error_log(
            tool="create_ticket.py",
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
