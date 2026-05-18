"""
Tool: run_contract_logging_agent.py
Purpose: Local one-shot test for Contract Logging Phase 1.
"""

import argparse
import json

from build_contract_card import (
    build_audit_card,
    build_confirmation_card,
    build_contract_created_card,
    prepare_contract_details,
)
from create_contract_in_portal import create_contract_in_portal, open_new_contract_for_recording
from fetch_jira_ticket import fetch_jira_ticket
from navigate_contract_page import navigate_to_contract_page
from notify_teams import post_card


def run(
    ticket_id: str,
    post_to_teams: bool = False,
    teams_target: str = "main",
    navigate: bool = False,
    create_contract: bool = False,
    overrides: dict | None = None,
) -> dict:
    ticket = fetch_jira_ticket(ticket_id)
    if ticket is None:
        raise RuntimeError(f"Ticket {ticket_id} not found")

    details = prepare_contract_details(ticket)
    if overrides:
        details.update({key: value for key, value in overrides.items() if value})
    confirmation_card = build_confirmation_card(details)

    result = {
        "ticket_id": ticket_id,
        "details": details,
        "confirmation_card": confirmation_card,
        "teams_card_posted": False,
        "navigation": None,
        "contract_number": None,
    }

    if post_to_teams:
        post_card(confirmation_card, target=teams_target)
        result["teams_card_posted"] = True

    if navigate:
        nav = navigate_to_contract_page()
        result["navigation"] = nav
        audit_card = build_audit_card(details)
        if post_to_teams:
            post_card(audit_card, target=teams_target)

    if create_contract:
        contract_number = create_contract_in_portal(details, ticket_id)
        result["contract_number"] = contract_number
        if post_to_teams:
            post_card(build_contract_created_card(ticket_id, contract_number), target=teams_target)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Contract Logging Phase 1 locally.")
    parser.add_argument("ticket_id", nargs="?", help="Jira ticket id, for example O360-15342")
    parser.add_argument("--post-to-teams", action="store_true", help="Post card to Teams")
    parser.add_argument(
        "--teams-target",
        choices=["testing", "main"],
        default="main",
        help="Teams destination for local test posts. Default: main.",
    )
    parser.add_argument("--navigate", action="store_true", help="Login and navigate to Contract page")
    parser.add_argument(
        "--create-contract",
        action="store_true",
        help="Open New Contract form, fill confirmed details, wait for Save, and extract contract number.",
    )
    parser.add_argument(
        "--open-new-only",
        action="store_true",
        help="Login, open the New Contract modal, then pause for manual recording/debugging.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=1800,
        help="How long to keep the browser open with --open-new-only. Default: 1800 seconds.",
    )
    parser.add_argument(
        "--inspector",
        action="store_true",
        help="Open Playwright Inspector after the New Contract modal is ready.",
    )
    parser.add_argument("--distribution-channel", help="Override Distribution Channel, for example OEM")
    parser.add_argument("--po-number", help="Override PO Number")
    parser.add_argument("--po-date", help="Override PO Date in DD/MM/YYYY")
    parser.add_argument("--contract-end-date", help="Override Contract End Date in DD/MM/YYYY")
    args = parser.parse_args()
    if args.open_new_only:
        open_new_contract_for_recording(args.hold_seconds, inspector=args.inspector)
        return
    if not args.ticket_id:
        parser.error("ticket_id is required unless --open-new-only is used")
    print(
        json.dumps(
            run(
                args.ticket_id.upper(),
                post_to_teams=args.post_to_teams,
                teams_target=args.teams_target,
                navigate=args.navigate,
                create_contract=args.create_contract,
                overrides={
                    "distribution_channel": args.distribution_channel,
                    "po_number": args.po_number,
                    "po_date": args.po_date,
                    "contract_end_date": args.contract_end_date,
                },
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
