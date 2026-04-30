# Tool Name   : Contract Status Agent Run Loop
# Skill       : Contract Status Agent
# Version     : 1.0.0
# Last Updated: 2026-04-30
# Description : Single-run orchestrator for the Contract Status Agent. Scrapes
#               Salesforce contracts, compares against the previous memory snapshot,
#               updates the Excel tracker via Power Automate, sends Teams status-change
#               notifications, and persists the latest snapshot.
# Dependencies: playwright, requests, openpyxl, python-dotenv, google-cloud-storage
# ENV Vars    : SF_PORTAL_URL, SF_USERNAME, SF_PASSWORD, PLAYWRIGHT_HEADLESS,
#               PA_EXCEL_URL, PA_TEAMS_URL, DRY_RUN, GCS_MEMORY_BUCKET,
#               GCS_MEMORY_BLOB
# GCP Note    : Designed as a one-shot function for Cloud Scheduler invocation every
#               15 minutes. Do not run an infinite loop inside Cloud Functions.

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path


SKILL_NAME = "Contract Status Agent"
TOOL_NAME = "run_contract_status_agent.py"
BASE_DIR = Path(__file__).parent.parent
TOOLS_DIR = Path(__file__).parent
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"
LOG_PATH = BASE_DIR / "Logs" / "error.log"
LATEST_SCRAPE_PATH = TOOLS_DIR / "last_scraped_contracts.json"


def utc_now():
    return datetime.utcnow().isoformat()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scraper = load_module("scrape_contract_statuses", TOOLS_DIR / "scrape_contract_statuses.py")
excel_updater = load_module("update_excel_via_pa", TOOLS_DIR / "update_excel_via_pa.py")
teams_notifier = load_module("notify_teams_via_pa", TOOLS_DIR / "notify_teams_via_pa.py")
memory_store_module = load_module("memory_store", TOOLS_DIR / "memory_store.py")
memory_store = memory_store_module.MemoryStore(MEMORY_PATH)


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
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_memory():
    return memory_store.read()


def write_memory(memory):
    memory_store.write(memory)


def start_run(memory, run_id):
    run_entry = {
        "run_id": run_id,
        "run_start": utc_now(),
        "run_end": None,
        "contracts_fetched": 0,
        "contracts_changed": 0,
        "excel_updated": None,
        "teams_notified": 0,
        "run_status": "running",
        "steps": [],
    }
    memory.setdefault("state", {}).setdefault("run_history", []).append(run_entry)
    memory["last_action"] = f"Started Contract Status Agent run {run_id}"
    write_memory(memory)
    return run_entry


def add_step(memory, step, status, detail="", extra=None):
    step_entry = {
        "step": step,
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
    write_memory(memory)


def finish_run(memory, run_status, detail, extra=None):
    run_history = memory.setdefault("state", {}).setdefault("run_history", [])
    if run_history:
        run_history[-1]["run_end"] = utc_now()
        run_history[-1]["run_status"] = run_status
        if extra:
            run_history[-1].update(extra)
    memory["last_run"] = utc_now()
    memory["last_action"] = detail
    write_memory(memory)


def normalize_contract(contract):
    return {
        "status": str(contract.get("status", "")).strip(),
        "account_name": str(contract.get("account_name", "")).strip(),
        "created_date": str(contract.get("created_date", "")).strip(),
    }


def build_snapshot(contracts):
    snapshot = {}
    for contract in contracts:
        contract_no = str(contract.get("contract_no", "")).strip()
        if not contract_no:
            continue
        snapshot[contract_no] = normalize_contract(contract)
    return snapshot


def compare_snapshots(previous_snapshot, current_snapshot):
    changes = []
    if not previous_snapshot:
        return changes

    for contract_no, current in current_snapshot.items():
        previous = previous_snapshot.get(contract_no)
        if not previous:
            continue
        previous_status = str(previous.get("status", "")).strip()
        new_status = str(current.get("status", "")).strip()
        if previous_status and new_status and previous_status != new_status:
            changes.append(
                {
                    "contract_no": contract_no,
                    "account_name": current.get("account_name", ""),
                    "created_date": current.get("created_date", ""),
                    "previous_status": previous_status,
                    "new_status": new_status,
                }
            )
    return changes


def run_once(run_id=None):
    run_id = run_id or "run_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    memory = read_memory()
    start_run(memory, run_id)

    try:
        previous_snapshot = memory.setdefault("state", {}).get("status_snapshot") or {}
        add_step(
            memory,
            "load_snapshot",
            "success",
            f"Loaded previous snapshot with {len(previous_snapshot)} contracts",
        )

        contracts = scraper.run(run_id, memory)
        if not memory_store.using_gcs:
            LATEST_SCRAPE_PATH.write_text(json.dumps(contracts, indent=2), encoding="utf-8")
        current_snapshot = build_snapshot(contracts)

        run_history = memory["state"]["run_history"]
        run_history[-1]["contracts_fetched"] = len(contracts)
        add_step(
            memory,
            "browser_scrape",
            "success",
            f"Scraped {len(contracts)} contracts from Salesforce portal",
            extra={"contracts_fetched": len(contracts)},
        )

        if not contracts:
            finish_run(
                memory,
                "failed",
                "Run failed because scraper returned zero contracts",
                extra={"contracts_fetched": 0, "contracts_changed": 0, "excel_updated": False},
            )
            return {
                "run_id": run_id,
                "run_status": "failed",
                "contracts_fetched": 0,
                "contracts_changed": 0,
                "excel_updated": False,
                "teams_notified": 0,
            }

        changes = compare_snapshots(previous_snapshot, current_snapshot)
        memory["state"]["run_history"][-1]["contracts_changed"] = len(changes)
        add_step(
            memory,
            "compare_snapshot",
            "success",
            f"Identified {len(changes)} status changes",
            extra={"contracts_changed": len(changes)},
        )

        excel_result = excel_updater.update_excel(contracts, run_id=run_id, memory=memory)
        excel_updated = excel_result.get("excel_updated")
        memory["state"]["run_history"][-1]["excel_updated"] = excel_updated

        if changes:
            teams_result = teams_notifier.notify_changes(changes, run_id=run_id, memory=memory)
            teams_notified = teams_result["succeeded"]
        else:
            teams_notified = 0
            add_step(
                memory,
                "teams_notify",
                "skipped",
                "No status changes found; Teams notification skipped",
                extra={"teams_notified": 0},
            )

        memory["state"]["run_history"][-1]["teams_notified"] = teams_notified

        memory["state"]["status_snapshot"] = current_snapshot
        add_step(
            memory,
            "snapshot_save",
            "success",
            f"Saved latest snapshot with {len(current_snapshot)} contracts",
        )

        finish_run(
            memory,
            "success",
            "Contract Status Agent run complete",
            extra={
                "contracts_fetched": len(contracts),
                "contracts_changed": len(changes),
                "excel_updated": excel_updated,
                "teams_notified": teams_notified,
            },
        )
        return {
            "run_id": run_id,
            "run_status": "success",
            "contracts_fetched": len(contracts),
            "contracts_changed": len(changes),
            "excel_updated": excel_updated,
            "teams_notified": teams_notified,
            "memory_backend": "gcs" if memory_store.using_gcs else "local",
            "note": "HTTP 202 from Power Automate means flow triggered; final Excel/Teams delivery is confirmed in PA run history.",
        }

    except Exception as e:
        log_error(run_id, "run_once", type(e).__name__, str(e), status="failed")
        memory = read_memory()
        finish_run(memory, "failed", f"Contract Status Agent run failed: {e}")
        raise


def cloud_function_entry(request):
    """HTTP entry point for future GCP Cloud Function deployment."""
    result = run_once()
    return json.dumps(result), 200, {"Content-Type": "application/json"}


def main():
    parser = argparse.ArgumentParser(description="Run the Contract Status Agent once.")
    parser.add_argument("--run-id", default=None, help="Optional run id for memory/error logging.")
    args = parser.parse_args()
    result = run_once(run_id=args.run_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
