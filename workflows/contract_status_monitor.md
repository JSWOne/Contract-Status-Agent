# Workflow: Contract Status Monitor

## Objective
Automatically detect Salesforce contract status changes and alert the Teams **Contract Status** channel in real time.

## Trigger
Background poll — runs every **15 minutes** automatically on server startup.

## Tools Used
- `tools/salesforce_contract_monitor.py` — Playwright scraper for Salesforce
- `tools/webhook_listener.py` — Flask server + monitor thread

## Flow
1. On startup, `webhook_listener.py` launches a background thread.
2. Thread calls `initialize_session()` — logs into Salesforce via Playwright, saves cookies to `.tmp/sf_session.json`.
3. Every 15 minutes, calls `check_for_changes()`:
   - Scrapes all contracts from Salesforce JSW One All Contracts list view.
   - Merges into `.tmp/contracts_master.json`.
   - Filters to last 30 days only.
   - Compares current status vs previous status per contract.
4. For each status change detected, posts an Adaptive Card to Teams via `TEAMS_CONTRACT_STATUS_WEBHOOK_URL`.
5. Also updates `.tmp/JSW ONE Agent SO Live Tracker.xlsx` with sheets:
   - All SO, In Approval Process, Draft, Activated, Closed, Not Approved.

## Output
- Teams **Contract Status** channel receives an Adaptive Card per change.
- Excel tracker updated at `.tmp/JSW ONE Agent SO Live Tracker.xlsx`.

## Environment Variables Required
| Variable | Purpose |
|----------|---------|
| `SALESFORCE_URL` | Salesforce login URL |
| `SALESFORCE_USERNAME` | Login email |
| `SALESFORCE_PASSWORD` | Login password |
| `TEAMS_CONTRACT_STATUS_WEBHOOK_URL` | Power Automate flow URL for Contract Status channel |

## Deployment
```bash
pip install -r requirements.txt
playwright install chromium
python tools/webhook_listener.py
```

## Edge Cases
- If Salesforce login times out: retries every 5 minutes.
- If scrape fails: logs error, sleeps, retries next poll cycle.
- Permission denied on Excel file (file open in Excel): logged and skipped — does not crash the monitor.
