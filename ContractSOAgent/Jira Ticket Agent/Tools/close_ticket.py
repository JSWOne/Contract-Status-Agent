"""
Tool Name   : close_ticket.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : Transition Jira tickets to Done and move them from pending to completed memory.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import argparse
import json
import os

from jira_client import JiraAgentError, JiraClient, load_memory, save_memory, utc_now, write_error_log


def close_ticket(ticket_id: str, resolution_comment: str | None = None) -> dict:
    client = JiraClient()

    if resolution_comment:
        client.add_comment(ticket_id, resolution_comment)

    transition_id = os.getenv("JIRA_DONE_TRANSITION_ID", "").strip()
    if not transition_id:
        done_name = os.getenv("JIRA_DONE_TRANSITION_NAME", "Done").strip().lower()
        transitions = client.get_transitions(ticket_id)
        match = next(
            (
                transition
                for transition in transitions
                if transition.get("name", "").strip().lower() == done_name
            ),
            None,
        )
        if not match:
            names = ", ".join(t.get("name", "") for t in transitions)
            raise ValueError(f"No Done transition found for {ticket_id}. Available: {names}")
        transition_id = match["id"]

    client.transition_issue(ticket_id, transition_id)

    memory = load_memory()
    state = memory.setdefault("state", {})
    pending = state.setdefault("pending_items", [])
    completed = state.setdefault("completed_items", [])

    closed_item = None
    remaining = []
    for item in pending:
        if item.get("ticket_id") == ticket_id:
            closed_item = item
        else:
            remaining.append(item)

    if closed_item:
        closed_item["status"] = "Done"
        closed_item["closed_at"] = utc_now()
        completed.append(closed_item)
        state["pending_items"] = remaining
    else:
        completed.append({"ticket_id": ticket_id, "status": "Done", "closed_at": utc_now()})

    save_memory(memory, f"closed Jira ticket {ticket_id}")
    return {"ok": True, "ticket_id": ticket_id, "status": "Done"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Close a Jira ticket.")
    parser.add_argument("ticket_id")
    parser.add_argument("--comment")
    args = parser.parse_args()

    try:
        print(json.dumps(close_ticket(args.ticket_id, args.comment), indent=2))
        return 0
    except (JiraAgentError, ValueError) as exc:
        write_error_log(
            tool="close_ticket.py",
            error_code=type(exc).__name__,
            error_message=str(exc),
            ticket_id=args.ticket_id,
        )
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
