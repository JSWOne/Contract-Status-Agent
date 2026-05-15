"""
Tool Name   : update_ticket.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : Add comments to existing Jira tickets and update Jira Ticket Agent memory.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import argparse
import json

from jira_client import JiraAgentError, JiraClient, load_memory, save_memory, utc_now, write_error_log


def update_ticket(ticket_id: str, comment: str, status: str | None = None) -> dict:
    client = JiraClient()
    client.add_comment(ticket_id, comment)

    memory = load_memory()
    for item in memory.setdefault("state", {}).setdefault("pending_items", []):
        if item.get("ticket_id") == ticket_id:
            item["last_seen"] = utc_now()
            if status:
                item["status"] = status
            break

    save_memory(memory, f"updated Jira ticket {ticket_id}")
    return {"ok": True, "ticket_id": ticket_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="Update a Jira ticket.")
    parser.add_argument("ticket_id")
    parser.add_argument("--comment", required=True)
    parser.add_argument("--status")
    args = parser.parse_args()

    try:
        print(json.dumps(update_ticket(args.ticket_id, args.comment, args.status), indent=2))
        return 0
    except JiraAgentError as exc:
        write_error_log(
            tool="update_ticket.py",
            error_code=type(exc).__name__,
            error_message=str(exc),
            ticket_id=args.ticket_id,
        )
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
