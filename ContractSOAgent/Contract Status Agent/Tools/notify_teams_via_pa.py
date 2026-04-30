# Tool Name   : Teams Status Change Notifier via Power Automate
# Skill       : Contract Status Agent
# Version     : 1.0.0
# Last Updated: 2026-04-30
# Description : For each contract whose status changed since the last run, POSTs a
#               structured payload to the Power Automate Teams-notify flow. The PA flow
#               renders an Adaptive Card in the "Contract Status" Teams channel.
# Dependencies: requests, python-dotenv
# ENV Vars    : PA_TEAMS_URL, DRY_RUN
# DRY_RUN     : Prints each payload to console; skips all POST calls

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))

DRY_RUN = os.getenv("DRY_RUN", "True").strip().lower() == "true"
PA_TEAMS_URL = os.getenv("PA_TEAMS_URL")

TOOL_NAME = "notify_teams_via_pa.py"
SKILL_NAME = "Contract Status Agent"
MEMORY_PATH = Path(__file__).parent.parent / "Memory" / "memory.json"
LOG_PATH = Path("/tmp/error.log") if os.environ.get("GCS_MEMORY_BUCKET") else Path(__file__).parent.parent / "Logs" / "error.log"


def utc_now():
    return datetime.utcnow().isoformat()


def log_error(
    run_id,
    step,
    error_code,
    error_message,
    payload=None,
    resolution=None,
    status="pending",
    ticket_id=None,
    learning=None,
):
    entry = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "skill": SKILL_NAME,
        "tool": TOOL_NAME,
        "step": step,
        "error_code": error_code,
        "error_message": error_message,
        "input_payload": payload or {},
        "context": step,
        "resolution_attempted": resolution,
        "resolution_status": status,
        "learning": learning,
        "ticket_id": ticket_id,
    }
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as log_exc:
        import sys
        print(json.dumps(entry), file=sys.stderr)
        print(f"[log_error] Could not write to {LOG_PATH}: {log_exc}", file=sys.stderr)


def read_memory():
    if MEMORY_PATH.exists():
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    return {
        "skill": SKILL_NAME,
        "last_run": None,
        "last_action": None,
        "state": {"run_history": []},
        "known_issues": [],
    }


def write_memory_step(memory, step_name, status, detail="", extra=None):
    step_entry = {
        "step": step_name,
        "status": status,
        "detail": detail,
        "timestamp": utc_now(),
    }
    if extra:
        step_entry.update(extra)

    run_history = memory.setdefault("state", {}).setdefault("run_history", [])
    if run_history:
        run_history[-1].setdefault("steps", []).append(step_entry)

    memory["last_action"] = detail
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def normalize_change(change):
    previous_status = (
        change.get("previous_status")
        or change.get("old_status")
        or change.get("from_status")
        or ""
    )
    new_status = (
        change.get("new_status")
        or change.get("status")
        or change.get("to_status")
        or ""
    )
    return {
        "contract_no": str(change.get("contract_no", "")).strip(),
        "account_name": str(change.get("account_name", "")).strip(),
        "created_date": str(change.get("created_date", "")).strip(),
        "previous_status": str(previous_status).strip(),
        "new_status": str(new_status).strip(),
    }


def validate_change_payload(payload):
    missing = [
        field
        for field in ("contract_no", "account_name", "previous_status", "new_status")
        if not payload.get(field)
    ]
    if missing:
        raise ValueError(f"Missing required Teams payload fields: {', '.join(missing)}")


def build_adaptive_card(payload):
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "Contract Status Changed",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": payload["account_name"],
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Contract No.", "value": payload["contract_no"]},
                    {"title": "Created Date", "value": payload["created_date"] or "-"},
                    {"title": "Previous Status", "value": payload["previous_status"]},
                    {"title": "New Status", "value": payload["new_status"]},
                ],
            },
        ],
    }


def build_request_payload(change):
    payload = normalize_change(change)
    validate_change_payload(payload)
    payload["adaptive_card"] = build_adaptive_card(payload)
    payload["adaptive_card_json"] = json.dumps(payload["adaptive_card"])
    return payload


def notify_one(change, run_id="run_manual", memory=None):
    memory = memory or read_memory()
    payload = build_request_payload(change)
    contract_no = payload["contract_no"]

    if DRY_RUN:
        detail = f"DRY_RUN: Teams notification prepared for contract {contract_no}"
        print(json.dumps(payload, indent=2))
        write_memory_step(
            memory,
            "teams_notify",
            "skipped",
            detail,
            extra={"contract_no": contract_no, "teams_notified": False, "dry_run": True},
        )
        return {
            "contract_no": contract_no,
            "teams_notified": False,
            "dry_run": True,
            "payload": payload,
        }

    if not PA_TEAMS_URL:
        message = "PA_TEAMS_URL is missing from .env"
        log_error(run_id, "teams_notify", "PA_CONFIG_MISSING", message, status="failed")
        write_memory_step(
            memory,
            "teams_notify",
            "failed",
            message,
            extra={"contract_no": contract_no, "teams_notified": False},
        )
        raise RuntimeError(message)

    try:
        response = requests.post(PA_TEAMS_URL, json=payload, timeout=60)
        if 400 <= response.status_code < 500:
            raise requests.HTTPError(f"PA_4XX {response.status_code}: {response.text}")
        if response.status_code >= 500:
            raise requests.HTTPError(f"PA_500 {response.status_code}: {response.text}")
        response.raise_for_status()

        if response.status_code == 202:
            detail = (
                f"Power Automate flow accepted Teams notification for contract {contract_no}; "
                "check flow run history for final delivery status"
            )
            teams_notified = None
        else:
            detail = f"Teams notification sent for contract {contract_no}"
            teams_notified = True

        write_memory_step(
            memory,
            "teams_notify",
            "success",
            detail,
            extra={
                "contract_no": contract_no,
                "teams_notified": teams_notified,
                "flow_triggered": True,
                "status_code": response.status_code,
            },
        )
        return {
            "contract_no": contract_no,
            "teams_notified": teams_notified,
            "flow_triggered": True,
            "dry_run": False,
            "status_code": response.status_code,
            "note": "HTTP 202 means the flow was triggered; confirm final delivery in Power Automate run history.",
        }

    except requests.HTTPError as e:
        error_code = "PA_500" if "PA_500" in str(e) else "PA_4XX"
        log_error(
            run_id,
            "teams_notify",
            error_code,
            str(e),
            payload=payload,
            status="failed",
        )
        write_memory_step(
            memory,
            "teams_notify",
            "failed",
            str(e),
            extra={"contract_no": contract_no, "teams_notified": False},
        )
        raise

    except requests.RequestException as e:
        log_error(
            run_id,
            "teams_notify",
            "TEAMS_NOTIFY_FAIL",
            str(e),
            payload=payload,
            resolution="Check PA_TEAMS_URL and network connectivity; retry once from orchestrator",
            status="pending",
        )
        write_memory_step(
            memory,
            "teams_notify",
            "failed",
            str(e),
            extra={"contract_no": contract_no, "teams_notified": False},
        )
        raise


def notify_changes(changes, run_id="run_manual", memory=None, continue_on_error=True):
    if not isinstance(changes, list):
        raise ValueError("changes must be a list of dictionaries")

    memory = memory or read_memory()
    results = []
    errors = []

    for change in changes:
        try:
            results.append(notify_one(change, run_id=run_id, memory=memory))
        except Exception as e:
            normalized = normalize_change(change)
            errors.append(
                {
                    "contract_no": normalized.get("contract_no"),
                    "error": str(e),
                }
            )
            if not continue_on_error:
                raise

    detail = (
        f"Teams notification flow triggered for {len(results)} status changes"
        if not errors
        else f"Teams notification completed with {len(results)} successes and {len(errors)} failures"
    )
    write_memory_step(
        memory,
        "teams_notify_summary",
        "success" if not errors else "partial",
        detail,
        extra={
            "teams_notified": len(results),
            "teams_failed": len(errors),
        },
    )
    return {
        "requested": len(changes),
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def load_changes_from_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "changes" in data:
        data = data["changes"]
    if not isinstance(data, list):
        raise ValueError("JSON input must be a list, or an object with a 'changes' list")
    return data


def main():
    parser = argparse.ArgumentParser(description="Notify Teams about Contract status changes via Power Automate.")
    parser.add_argument("--changes-json", required=True, help="Path to JSON file containing status-change records.")
    parser.add_argument("--run-id", default="run_manual", help="Run id for memory/error logging.")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop after the first notification failure.",
    )
    args = parser.parse_args()

    changes = load_changes_from_json(args.changes_json)
    result = notify_changes(
        changes,
        run_id=args.run_id,
        continue_on_error=not args.stop_on_error,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
