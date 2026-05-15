"""
Tool Name   : run_jira_ticket_agent.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : CLI dispatcher for Jira Ticket Agent create, update, and close operations.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import argparse
import json
import sys

from close_ticket import close_ticket
from create_ticket import create_or_update_ticket
from update_ticket import update_ticket


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Jira Ticket Agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--payload")
    create_parser.add_argument("--payload-file")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("ticket_id")
    update_parser.add_argument("--comment", required=True)
    update_parser.add_argument("--status")

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("ticket_id")
    close_parser.add_argument("--comment")

    args = parser.parse_args()

    if args.command == "create":
        if args.payload_file:
            with open(args.payload_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        elif args.payload:
            payload = json.loads(args.payload)
        else:
            payload = json.load(sys.stdin)
        result = create_or_update_ticket(payload)
    elif args.command == "update":
        result = update_ticket(args.ticket_id, args.comment, args.status)
    else:
        result = close_ticket(args.ticket_id, args.comment)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
