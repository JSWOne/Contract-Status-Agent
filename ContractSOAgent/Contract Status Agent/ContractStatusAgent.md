# ContractStatusAgent — Skill Instructions
> **Parent Orchestrator:** ContractSOAgent
> Version: 2.9.0 | Phase: 2 | Status: Cloud Run Repo Updated; Env Vars + Scheduler Pending | Last Updated: 2026-04-30

---

## 0. Build Status

| Tool | Status | Notes |
|------|--------|-------|
| `scrape_contract_statuses.py` | Complete & Tested | 357 contracts/14 days confirmed on 2026-04-30; descending Created Date + infinite scroll working |
| `update_excel_via_pa.py` | Complete & Tested | Builds `LIVE Contracts` workbook and triggers PA Excel-update flow; confirmed Excel tracker updated after closing locked workbook |
| `notify_teams_via_pa.py` | Complete & Tested | Sends valid `adaptive_card` payload to PA Teams flow; confirmed card posted to Teams channel |
| `run_contract_status_agent.py` | Complete & Tested | One-shot local orchestrator; scraped 360 contracts, updated Excel flow, saved baseline snapshot |
| Cloud Run deployment package | Complete | `main.py`, root `requirements.txt`, `Dockerfile`, and `.dockerignore` added |
| GCS memory persistence | Complete | `memory_store.py` added; runner uses GCS when `GCS_MEMORY_BUCKET` is configured |
| Cloud Run-connected repo cleanup | Complete | Current code pushed to `JSWOne/Contract-Status-Agent`; old `tools/` and `workflows/` code removed in commit `e172cfd` |

---

## 1. Objective

Every **15 minutes**, this agent:

1. Scrapes the JSW Steel Salesforce portal for all **Contract** records with `CreatedDate >= LAST_N_DAYS:14` (rolling 2-week window from today).
2. Syncs the full contract list to the **SO Contract AI Agent.xlsx** Excel tracker on OneDrive via the Power Automate Excel-update flow.
3. Compares the current Salesforce snapshot against the previous run's snapshot stored in `Memory/memory.json`.
4. For every contract whose **Status has changed** since the last run → triggers the Power Automate Teams-notify flow to post a formatted status-change card to the **Contract Status** channel in the **SO Contract Agent** Microsoft Teams team.

At every step, the agent writes its progress to `Memory/memory.json` and any errors to `Logs/error.log`. Before attempting any tool call, the agent checks `error.log` for previously seen errors and applies known resolutions automatically — so it never debugs the same issue twice.

---

## 2. Inputs

| Field | Source | Required |
|-------|--------|----------|
| Date window | Last 14 days from today (filtered by Created Date on portal) | Yes |
| Previous status snapshot | `Memory/memory.json → state.status_snapshot` | Yes (empty dict on first run) |
| Salesforce portal URL | `SF_PORTAL_URL` in `.env` | Yes |
| Salesforce login credentials | `SF_USERNAME`, `SF_PASSWORD` in `.env` | Yes |

---

## 3. Outputs

| Output | Destination |
|--------|-------------|
| Updated Excel (all contracts, last 14 days) | Power Automate Excel-update flow → OneDrive `SO Contract AI Agent.xlsx` |
| Status-change Teams card (per changed contract) | Power Automate Teams-notify flow → "Contract Status" channel in "SO Contract Agent" team |
| Updated status snapshot | `Memory/memory.json → state.status_snapshot` |
| Step-by-step run log | `Memory/memory.json → state.run_history` |
| Error + resolution entries | `Logs/error.log` (NDJSON, append-only) |

---

## 4. Tools/ Folder Contents

### 4.1 Support Files

| File | Purpose |
|------|---------|
| `requirements.txt` | pip dependencies — `playwright`, `openpyxl`, `requests`, `python-dotenv` |
| `.env` | Live secrets and config values (never commit to version control) |
| `.env.example` | Blank template with all required keys — safe to commit |
| `.gitignore` | Excludes `.env` and `config/token.json` from version control |

Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

---

### 4.2 Python Tool Scripts

| Script | Status | Purpose |
|--------|--------|---------|
| `scrape_contract_statuses.py` | ✅ Complete | Playwright browser automation — logs into JSW Steel Salesforce portal, navigates to Contracts list, sorts descending, infinite-scrolls all 14-day contracts |
| `update_excel_via_pa.py` | Complete | Build `.xlsx` in-memory with `LIVE Contracts` sheet → base64-encode → POST to PA Excel-update flow |
| `notify_teams_via_pa.py` | Complete | POST status-change payload with valid Adaptive Card object to PA Teams-notify flow (one call per changed contract) |
| `run_contract_status_agent.py` | Complete | One-shot orchestrator for local testing and future Cloud Scheduler/Cloud Run invocation |
| `memory_store.py` | Complete | Reads/writes memory locally by default, or in Google Cloud Storage when `GCS_MEMORY_BUCKET` is set |

> **Note:** `refresh_token.py` is not required — authentication is handled by Playwright logging into the Salesforce portal directly with `SF_USERNAME` and `SF_PASSWORD`. No OAuth2 API credentials are needed.

### 4.2.1 Cloud Run Deployment Files

These files live at the repository root and are present in the Cloud Run-connected repo `JSWOne/Contract-Status-Agent`.

| File | Status | Purpose |
|------|--------|---------|
| `main.py` | Added | Flask HTTP wrapper for Cloud Run. `GET /` returns health status; `GET/POST /run` executes one Contract Status Agent run. |
| `Dockerfile` | Added | Container build using `mcr.microsoft.com/playwright/python:v1.56.0-noble`, so Chromium and Playwright system dependencies are available. |
| `requirements.txt` | Added | Root deployment dependencies: `flask`, `gunicorn`, `openpyxl`, `playwright`, `python-dotenv`, `requests`. |
| `.dockerignore` | Added | Excludes `.env`, memory files, logs, scraped JSON, pycache, and git metadata from the container build. |

**Cloud Run HTTP Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | `GET` | Health check. Returns `{"service": "contract-status-agent", "status": "ok"}`. |
| `/run` | `GET` or `POST` | Runs the full agent once: scrape, compare, update Excel, notify Teams, save snapshot. |

`POST /run` can optionally receive:

```json
{
  "run_id": "manual_or_scheduler_run_id"
}
```

**Container Runtime Command:**

```bash
gunicorn --bind :${PORT:-8080} --workers 1 --threads 1 --timeout 900 main:app
```

Use one worker/thread for now to avoid two concurrent Cloud Run requests writing the same memory snapshot at the same time. Cloud Run max instances/concurrency should also be kept conservative until GCS locking or another durable state strategy is added.

All scripts share these conventions (per ContractSOAgent standards):
- `DRY_RUN = True/False` flag at top of every file — when `True`, skips all POST/browser-write calls and prints payloads to console; memory and error.log writes still happen
- Secrets loaded from `.env` via `python-dotenv` — no hardcoded credentials
- Every operation wrapped in `try/except`; errors written to `Logs/error.log` before re-raising
- `PLAYWRIGHT_HEADLESS=True` runs the browser invisibly in the background; set to `False` to watch the browser during debugging

---

### 4.3 Tool Header Blocks

Each script must open with the following header (per ContractSOAgent Section 5.1 standard):

**`scrape_contract_statuses.py`**
```python
# Tool Name   : Salesforce Contract Status Scraper (Playwright)
# Skill       : Contract Status Agent
# Version     : 1.1.0
# Last Updated: 2026-04-30
# Description : Uses Playwright to log into the JSW Steel Salesforce Experience Cloud
#               portal, navigates directly to "JSW One All Contracts" list view, checks
#               aria-sort on Created Date th — if not descending, scrolls page to top
#               then clicks th[aria-label='Created Date'] a to sort descending. Uses
#               infinite scroll (scroll last row into view, stop when no growth for 3
#               consecutive scrolls) to load records. Extracts data via positional JS
#               evaluate (cells[1]=ContractNo, cells[2]=AccountName, cells[3]=Status,
#               cells[7]=CreatedDate). Early-stops when descending record age > 14 days.
#               Filters to last 14 days in Python. Returns list of dicts.
# Dependencies: playwright, python-dotenv
# ENV Vars    : SF_PORTAL_URL, SF_USERNAME, SF_PASSWORD, PLAYWRIGHT_HEADLESS
# DRY_RUN     : Runs browser + scrapes but skips writing; prints records to console only
```

**`update_excel_via_pa.py`**
```python
# Tool Name   : Excel Tracker Updater via Power Automate
# Skill       : Contract Status Agent
# Version     : 1.0.0
# Last Updated: 2026-04-30
# Description : Takes the contract list from scrape_contract_statuses.py, builds an
#               in-memory .xlsx file using openpyxl, base64-encodes the bytes, and
#               POSTs { "content": "<base64>" } to the Power Automate Excel-update flow.
#               PA flow uses base64ToBinary() to write the file to OneDrive.
# Dependencies: requests, openpyxl, python-dotenv
# ENV Vars    : PA_EXCEL_URL, DRY_RUN
# DRY_RUN     : Builds and encodes the Excel file but skips the POST; prints payload size.
# Runtime     : HTTP 202 means "flow triggered"; final success must be verified in
#               Power Automate run history because the flow runs asynchronously.
```

**`notify_teams_via_pa.py`**
```python
# Tool Name   : Teams Status Change Notifier via Power Automate
# Skill       : Contract Status Agent
# Version     : 1.0.0
# Last Updated: 2026-04-30
# Description : For each contract whose status changed since the last run, POSTs a
#               structured payload to the Power Automate Teams-notify flow. The PA flow
#               renders an Adaptive Card in the "Contract Status" Teams channel.
#               One HTTP call per changed contract.
# Dependencies: requests, python-dotenv
# ENV Vars    : PA_TEAMS_URL, DRY_RUN
# DRY_RUN     : Prints each payload to console; skips all POST calls
# Runtime     : Sends both adaptive_card (object) and adaptive_card_json (string fallback).
#               PA Teams action should use triggerBody()?['adaptive_card'].
```

---

## 5. Salesforce Portal Reference (Playwright)

Authentication is done via browser login — no REST API or OAuth2 credentials required.

| Parameter | Value |
|-----------|-------|
| Portal URL | `https://jswsteel.my.site.com/jswone/s/login/` |
| Login Method | Playwright fills username + password fields on the Salesforce login page |
| Username | `SF_USERNAME` from `.env` |
| Password | `SF_PASSWORD` from `.env` |
| Browser | Chromium (headless by default, controlled by `PLAYWRIGHT_HEADLESS`) |
| Contracts List URL | `https://jswsteel.my.site.com/jswone/s/recordlist/Contract/Default?Contract-filterId=JSW_One_All_Contracts` |

**Playwright Navigation Steps (confirmed 2026-04-30):**
1. Launch Chromium (`headless=PLAYWRIGHT_HEADLESS`, viewport 1280×800)
2. `page.goto(SF_PORTAL_URL, wait_until="domcontentloaded")`
3. Wait for `role=textbox[name='Username']` to be ready
4. Fill username via `get_by_role("textbox", name="Username")`
5. Fill password via `get_by_role("textbox", name="Password")`
6. Capture `login_url = page.url` before clicking
7. Click `get_by_role("button", name="Log in")`
8. Wait for URL to change away from login page: `page.wait_for_url(lambda url: url != login_url, timeout=60000)`
9. Wait for nav menu: `page.wait_for_selector("role=menuitem[name='Contract']", timeout=30000)`
10. Navigate directly to Contracts list: `page.goto(CONTRACTS_URL, wait_until="domcontentloaded")`
11. Wait for table rows: `page.wait_for_selector("table tbody tr", timeout=30000)`
12. **Sort descending** (CRITICAL — not just an optimisation):
    - Read `aria-sort` attribute on `th[aria-label*='Created Date']`
    - If already `"descending"` → skip (do nothing)
    - If `"ascending"` or absent → `page.evaluate("window.scrollTo(0, 0)")`, wait 500ms, then click `th[aria-label='Created Date'] a`
    - Fallback if no `<a>` inside th: `page.evaluate(getBoundingClientRect + elementFromPoint().click())`
    - Wait 2s → verify `aria-sort` is now `"descending"`
13. **Infinite scroll** to load records:
    - Scroll last visible `table tbody tr` into view: `all_rows[-1].scroll_into_view_if_needed()`
    - Wait 2s → check if row count increased
    - With descending sort: early-stop when `created_date < cutoff_date` (hits ~7 scrolls / 350 records for 14-day window)
    - End condition: row count unchanged for 3 consecutive scrolls
14. Close browser → return collected contracts

> **CRITICAL — Sort Direction Controls Which Records Load:** The portal caps the list at ~1300 scrollable records. With **ascending** sort (default), those 1300 are the *oldest* records (2024 data) — recent 2026 contracts never appear, 14-day filter returns 0. With **descending** sort, the first ~350 records are the most recent and cover the full 14-day window. Always sort descending before scraping.

> **Confirmed — No Pagination Buttons:** The JSW One All Contracts list view uses **infinite scroll** only. There is no "Next Page" button (`button[name='next']`, `button[aria-label='Next Page']`, etc. — all return 0 matches). Trigger new batches by scrolling the last row into view.

> **Sort Click — What Works and What Doesn't:**
> - ✅ `page.evaluate("window.scrollTo(0,0)")` then `page.locator("th[aria-label='Created Date'] a").click()`
> - ✅ Fallback: `getBoundingClientRect + elementFromPoint().click()` via `page.evaluate`
> - ❌ `sort_th.click()` — "Element is outside of the viewport" (Salesforce sticky header quirk)
> - ❌ `sort_th.click(force=True)` — same viewport error
> - ❌ `sort_th.evaluate("el => el.click()")` — Aura event system ignores JS `.click()`
> - ❌ `dispatch_event(MouseEvent)` — Aura ignores synthetic events
> - ❌ Column action dropdown "Sort Descending" — menu option text not found

**Salesforce Aura Table DOM Structure (confirmed 2026-04-30):**

The table uses Salesforce Aura components — cells do **NOT** have `data-label` attributes. Extract data by position using JavaScript:

```python
cells = row.evaluate(
    "el => [...el.querySelectorAll('th, td')].map(c => c.innerText.trim())"
)
```

| Index | Column | Example Value |
|-------|--------|---------------|
| `cells[0]` | Row error icon | `''` (empty) |
| `cells[1]` | Contract Number | `'00016161'` |
| `cells[2]` | Account Name | `'Satrac Engg Pvt Ltd'` |
| `cells[3]` | Status | `'Draft'` |
| `cells[4]` | Contract Start Date | `'07/07/2024'` |
| `cells[5]` | Contract End Date | `'07/09/2024'` |
| `cells[6]` | Contract Owner Alias | `'-'` |
| `cells[7]` | **Created Date** ← filter key | `'07/07/2024, 3:14 pm'` |
| `cells[8]` | Show Actions button | `'Show Actions'` |

> **Critical:** `cells[7]` is the Created Date (with timestamp). `cells[4]` is the Start Date — do NOT use it for the 14-day filter. The date format is `DD/MM/YYYY, H:MM am/pm`.

**Date Parsing** — formats tried in order:
```python
("%d/%m/%Y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
 "%d/%m/%Y %I:%M %p", "%Y-%m-%d",
 "%d/%m/%Y", "%m/%d/%Y")
```

**Table Row Selector:** `table tbody tr` (confirmed — finds 50 rows per scroll batch)

**Excel Column Mapping:**

| Scraped Field | Excel Column |
|--------------|--------------|
| Contract No (`cells[1]`) | A — Contract No |
| Account Name (`cells[2]`) | B — Account Name |
| Status (`cells[3]`) | C — Status |
| Created Date (`cells[7]`) | D — Created Date |

**Known Status Values:** `Draft`, `In Approval Process`, `Activated`, `Expired`

---

### 5.1 Debugging Notes (2026-04-30)

| Issue | Root Cause | Fix Applied |
|-------|-----------|-------------|
| LOGIN_FAIL | Used `if "login" in page.url` immediately after click — fired before redirect | Changed to `page.wait_for_url(lambda: url != login_url, timeout=60000)` |
| TIMEOUT on login | Used `wait_for_load_state("networkidle")` — Salesforce LWR never reaches networkidle | Replaced ALL networkidle waits with element-based `wait_for_selector` waits |
| Cells all timing out | Used `data-label` CSS selectors — Salesforce Aura tables have NO `data-label` attributes | Replaced with JS evaluate positional extraction (`cells[N]`) |
| Wrong date column | `cells[4]` is Start Date, not Created Date | Use `cells[7]` for Created Date (has timestamp) |
| No pagination | List view uses infinite scroll — no next button exists (all button selectors return 0) | Replaced pagination loop with `row.scroll_into_view_if_needed()` infinite scroll |
| 0 contracts in 14 days | Sort was ascending → loaded oldest 1300 records (2024), never reached 2026 contracts | Sort descending: `window.scrollTo(0,0)` then click `th[aria-label='Created Date'] a` |
| Sort `th` unclickable directly | `th` element is flagged "outside viewport" by Playwright (Salesforce sticky header quirk) | Scroll page to top first, then click the `<a>` anchor inside the `th`, not the `th` itself |

---

## 6. Power Automate API Reference

### 6.1 Excel Update Flow

Triggered once per run to overwrite the LIVE Contracts sheet with the current Salesforce snapshot.

| Parameter | Value |
|-----------|-------|
| Method | `POST` |
| URL | `PA_EXCEL_URL` from environment |
| Content-Type | `application/json` |
| Target File | `SO Contract AI Agent.xlsx` on OneDrive - JSW / Power Automate |

**Request Body Schema:**
```json
{
  "content": "<base64-encoded .xlsx bytes>"
}
```
`content` must be a **base64-encoded string** of the `.xlsx` file bytes. The PA flow uses `base64ToBinary(triggerBody()?['content'])` to decode it before writing to OneDrive. Confirmed from PA Code view.

**Python implementation:**
```python
import base64, io, openpyxl, requests

wb = openpyxl.Workbook()
ws = wb.active
# ... write rows ...
buf = io.BytesIO()
wb.save(buf)
b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
requests.post(PA_EXCEL_URL, json={"content": b64})
```

**Confirmed Excel Update Test (2026-04-30):**

- `scrape_contract_statuses.py` scraped `357` contracts for the rolling 14-day window.
- `update_excel_via_pa.py` built a workbook with the sheet name `LIVE Contracts`.
- Power Automate successfully updated `SO Contract AI Agent.xlsx` after the workbook was closed.
- A copy of the scraped input used for the test is stored at `Tools/last_scraped_contracts.json`.

**Power Automate Flow Details (confirmed 2026-04-30):**

| Flow Step | Confirmed Setting |
|-----------|-------------------|
| Get file metadata using path | `/Power Automate/SO Contract AI Agent.xlsx` |
| Update file - File | `/Power Automate/SO Contract AI Agent.xlsx` |
| Update file - File Content | `base64ToBinary(triggerBody()?['content'])` |

**Important Runtime Notes:**

- HTTP `202` from the flow trigger is not final Excel success. It only means Power Automate accepted the async run request.
- If the OneDrive path is wrong, `Get file metadata using path` fails with `NotFound`.
- If the workbook is open in Excel desktop or Excel Online, `Update file` fails because the file is locked for shared use.
- For unattended 15-minute runs, full file replacement is fragile if operators keep the workbook open. A future improvement should update an Excel table or run an Office Script instead of replacing the whole workbook.

---

### 6.2 Teams Notification Flow

Triggered once per changed contract to post a status-change card to Teams.

| Parameter | Value |
|-----------|-------|
| Method | `POST` |
| URL | `PA_TEAMS_URL` from environment |
| Content-Type | `application/json` |
| Target Channel | "Contract Status" in "SO Contract Agent" Teams team |

**Request Body Schema (one call per changed contract):**
```json
{
  "contract_no": "<ContractNumber>",
  "account_name": "<Account.Name>",
  "created_date": "<CreatedDate display string>",
  "previous_status": "<status from last snapshot>",
  "new_status": "<current status from Salesforce>",
  "adaptive_card": { "<valid Adaptive Card object>": "..." },
  "adaptive_card_json": "<valid Adaptive Card JSON string fallback>"
}
```

**Teams Card Format (as displayed in channel):**
```
⚡ Contract Status Changed
<Account Name>

Contract No.    <ContractNumber>
Created Date    <DD/MM/YYYY, H:MM am/pm>
Previous Status <previous_status>
New Status      <new_status>

[View Contract]
```

**Confirmed Teams Notification Test (2026-04-30):**

- `notify_teams_via_pa.py` sent a test status-change payload for contract `00171517`.
- The Power Automate Teams flow posted a card to the `Contract Status` channel in the `SO Contract Agent` team.
- The Teams action must use `triggerBody()?['adaptive_card']` in the **Adaptive Card** field.

**Power Automate Teams Flow Details (confirmed 2026-04-30):**

| Flow Step | Confirmed Setting |
|-----------|-------------------|
| Trigger | Manual HTTP POST |
| Teams action | Post card in a chat or channel |
| Post in | Channel |
| Team | `SO Contract Agent` |
| Channel | `Contract Status` |
| Adaptive Card | `triggerBody()?['adaptive_card']` |

**Important Runtime Notes:**

- HTTP `202` from the flow trigger is not final Teams delivery. It only means Power Automate accepted the async run request.
- Do not manually compose Adaptive Card JSON inside Power Automate using raw dynamic fields. That caused `message body is invalid JSON`.
- Python sends `adaptive_card` as a JSON object and `adaptive_card_json` as a fallback string. Use `adaptive_card` for the Teams action.

---

## 7. Schedule

| Parameter | Value |
|-----------|-------|
| Run interval | Every **15 minutes** |
| Trigger mechanism | Cloud Scheduler HTTP trigger to Cloud Run `/run` endpoint |
| Run logic | Fetch → Compare → Update Excel → Notify Teams (if changes) → Persist snapshot |
| Cloud Run service | `jsw-contract-status-agent` in `asia-south1` |
| GitHub repo | `https://github.com/JSWOne/Contract-Status-Agent` branch `main` |
| Deployment type | Repository build using root `Dockerfile` |

### 7.1 Cloud Run Deployment Status

| Item | Status | Notes |
|------|--------|-------|
| GitHub repo push | Complete | Current code pushed to Cloud Run-connected repo in commit `04d9ad6`; old repo code removed in commit `e172cfd`. |
| Cloud Run wrapper | Complete | `main.py` exposes `/` and `/run`. |
| Playwright container base | Complete | Dockerfile uses Microsoft Playwright Python image. |
| GCS bucket/object | Complete | Bucket `ai-for-jswone-contract-agent-state`; object `contract-status-agent/memory.json` uploaded. |
| GCS IAM permission | Complete | Cloud Run service account `729173585258-compute@developer.gserviceaccount.com` granted bucket access. |
| Environment variables | Pending in Cloud Run | Configure via Cloud Run env vars or Secret Manager before live run. |
| Persistent memory | Complete | `memory_store.py` uses Google Cloud Storage when `GCS_MEMORY_BUCKET` is set. |
| Scheduler | Pending | Add Cloud Scheduler job after Cloud Run service is deployed and tested manually. |

### 7.1.1 Production Deployment Pending Checklist

1. Confirm Cloud Build trigger uses repo `JSWOne/Contract-Status-Agent`, branch `main`, and root `Dockerfile`.
2. Trigger/verify a new Cloud Run build from commit `e172cfd` or newer.
3. Add Cloud Run environment variables listed in section 7.2.
4. Set Cloud Run runtime settings:
   - Timeout: `900s`
   - Container concurrency: `1`
   - Minimum instances: `1`
   - Maximum instances: `1`
5. Test health endpoint `/`.
6. Test one manual agent run via `/run`.
7. Verify:
   - Cloud Run logs show successful scrape.
   - Excel Power Automate flow succeeds.
   - GCS `contract-status-agent/memory.json` last modified timestamp updates.
   - Teams notification posts only when status changes are detected.
8. Create Cloud Scheduler job to call `/run` every 15 minutes.

### 7.2 Required Cloud Run Environment Variables

| Variable | Purpose |
|----------|---------|
| `SF_PORTAL_URL` | Salesforce portal login URL |
| `SF_USERNAME` | Salesforce portal username |
| `SF_PASSWORD` | Salesforce portal password |
| `PLAYWRIGHT_HEADLESS` | Must be `True` in Cloud Run |
| `PA_EXCEL_URL` | Power Automate Excel update HTTP trigger |
| `PA_TEAMS_URL` | Power Automate Teams notification HTTP trigger |
| `DRY_RUN` | `False` for production; `True` for payload-only testing |
| `GCS_MEMORY_BUCKET` | GCS bucket that stores the persisted memory JSON |
| `GCS_MEMORY_BLOB` | GCS object path, e.g. `contract-status-agent/memory.json` |

Recommended production handling: store secrets in Secret Manager and mount/inject them as Cloud Run environment variables.

---

## 8. Memory Schema & Update Protocol

`Memory/memory.json` is the agent's persistent brain. It is **read at the start** of every run and **written after every individual step** — not just at the end. This ensures that if a run is interrupted mid-way, the next run knows exactly where it stopped and what it already completed.

Over time, `run_history` and `known_issues` grow to form a full audit trail and self-training knowledge base.

### 8.1 Full Schema

```json
{
  "skill": "Contract Status Agent",
  "last_run": "<ISO timestamp of last completed run>",
  "last_action": "<description of the last step completed>",
  "state": {
    "last_processed_id": null,
    "pending_items": [],
    "completed_items": [],
    "status_snapshot": {
      "<ContractNumber>": {
        "status": "<last known status>",
        "account_name": "<account name>",
        "created_date": "<ISO date string>"
      }
    },
    "run_history": [
      {
        "run_id": "<auto-incremented run number e.g. run_001>",
        "run_start": "<ISO timestamp>",
        "run_end": "<ISO timestamp or null if still running>",
        "contracts_fetched": "<integer>",
        "contracts_changed": "<integer>",
        "excel_updated": "<true | false>",
        "teams_notified": "<integer — number of notifications sent>",
        "run_status": "success | partial | failed",
        "steps": [
          {
            "step": "<step name>",
            "status": "success | failed | skipped",
            "detail": "<brief outcome description>",
            "timestamp": "<ISO timestamp>"
          }
        ]
      }
    ]
  },
  "known_issues": [
    {
      "error_code": "<error identifier>",
      "description": "<what the error is>",
      "resolution": "<exact steps taken to resolve it>",
      "first_seen": "<ISO timestamp>",
      "last_seen": "<ISO timestamp>",
      "resolved_at": "<ISO timestamp>",
      "occurrence_count": "<integer — incremented each time this error repeats>",
      "learning": "<what this agent now knows because of this error>"
    }
  ]
}
```

### 8.2 When to Write Memory (Step-by-Step)

The agent writes `memory.json` **immediately after each step below completes** (success or failure):

| Step | What to write to memory |
|------|------------------------|
| Run starts | Add new entry to `run_history` with `run_start`, `run_id`, `run_status: "running"` |
| Token refresh done | Append `{ "step": "token_refresh", "status": "success/failed", ... }` to current run's `steps[]` |
| Salesforce query done | Append step with `contracts_fetched` count; also update `last_action` |
| Snapshot comparison done | Append step with `contracts_changed` count |
| Excel update done | Append step with `excel_updated: true/false` |
| Each Teams notification sent | Append step with `contract_no` and notification status |
| Snapshot saved | Overwrite `state.status_snapshot` with new data; append step |
| Run ends | Update `run_end`, `run_status`, `last_run`, `last_action` on the `run_history` entry |

### 8.3 How Memory Grows Over Time

- `run_history` accumulates every run — it is **appended, never overwritten**.
- `known_issues` grows each time the agent encounters and resolves a new error. `occurrence_count` increments each time an already-known error repeats.
- `status_snapshot` is always the latest state — it is overwritten each successful run.
- Periodically (every 100 runs or when `run_history` exceeds 500 entries), older run entries may be archived to a separate `memory_archive_<YYYY-MM>.json` file to keep the active file lean.

---

## 9. Error Log Protocol

`Logs/error.log` is the agent's self-learning error journal. Every error is written here with enough context to reproduce and resolve it. Before any tool is called, this log is checked — if the same error was seen before and resolved, the resolution is applied **proactively**, before the error even occurs.

### 9.1 Log Entry Format (NDJSON — one JSON object per line)

```json
{
  "timestamp": "<ISO timestamp>",
  "run_id": "<run_id from memory.json run_history>",
  "skill": "Contract Status Agent",
  "tool": "<script filename that was running>",
  "step": "<which step in the execution checklist>",
  "error_code": "<HTTP status code or Python exception type>",
  "error_message": "<full error string or traceback>",
  "input_payload": { },
  "context": "<what the agent was trying to do when this error occurred>",
  "resolution_attempted": "<description of auto-fix applied, or null>",
  "resolution_status": "success | failed | pending",
  "learning": "<what this error taught the agent — filled in on resolution>",
  "ticket_id": "<Jira ticket ID if raised, else null>"
}
```

### 9.2 Pre-Run Check (Before Every Tool Call)

```
1. Read Logs/error.log — scan last 20 entries
2. Filter entries where:
   - error_code matches the current tool/step context
   - resolution_status = "success"
3. If a matching resolved entry is found:
   a. Extract the resolution
   b. Apply it before calling the tool (e.g. pre-refresh token if 401 was seen before)
   c. Log a note in memory.json current run step: "preemptive fix applied from error.log"
4. If no matching entry → proceed normally
```

### 9.3 On Error (Immediate Actions)

```
1. Write error entry to Logs/error.log immediately (before any retry)
2. Check memory.json → known_issues for matching error_code
3. If match found:
   a. Apply the stored resolution
   b. Retry the tool call ONCE
   c. If retry succeeds → update error.log entry: resolution_status = "success", learning = "<what worked>"
                       → update known_issues: last_seen, occurrence_count++
   d. If retry fails  → resolution_status = "failed" → invoke Jira Ticket Agent → log ticket_id
4. If no match found:
   a. Attempt default auto-fix (see error handling table in section 10)
   b. Retry ONCE
   c. If retry succeeds → write full resolution to error.log + memory.json known_issues (new entry)
   d. If retry fails  → invoke Jira Ticket Agent → halt this run (other records continue)
```

### 9.4 On Resolution (Learning Update)

When an error is resolved (retry succeeded), the agent:
1. Updates the `error.log` entry in-place with `resolution_status: "success"` and fills `learning`.
2. Upserts `memory.json → known_issues`: if `error_code` already exists → increment `occurrence_count`, update `last_seen` and `resolution`; if new → add a fresh entry.
3. Updates `last_action` in memory to reflect the recovery.

This means every error the agent encounters makes it smarter for the next run.

---

## 10. Error Handling Reference

| Error Code | Step Where It Occurs | Description | Auto-fix |
|------------|---------------------|-------------|---------|
| `LOGIN_FAIL` | Browser login | Username/password rejected by Salesforce portal | Log credentials context (not password); raise P1 Jira; halt run |
| `TIMEOUT` | Any Playwright step | Page or element did not load within timeout | Retry once with increased timeout (60s); P2 Jira if still failing |
| `ELEMENT_NOT_FOUND` | Scraping | Expected DOM element (row, column, button) not found | Log page HTML snapshot to error.log; raise P2 Jira |
| `SCROLL_STALL` | Scraping | Infinite scroll stops loading new rows before all expected records appear | Log records scraped so far; continue with partial data; raise P3 Jira |
| `PORTAL_REDIRECT` | Browser login | Portal redirected to unexpected URL (SSO, MFA, etc.) | Log URL; raise P1 Jira; halt run — manual intervention required |
| `SCRAPE_EMPTY` | Scraping | Zero contracts returned despite valid login | Verify filter settings; raise P2 Jira |
| `PA_4XX` | Excel update / Teams notify | Power Automate rejected the request | Log full payload to error.log; raise P2 Jira |
| `PA_500` | Excel update / Teams notify | Power Automate server error | Wait 30s, retry once; P2 Jira if still failing |
| `TEAMS_NOTIFY_FAIL` | Teams notify | Teams flow failed after retry | P3 Jira; Excel update still proceeds |
| `MEMORY_WRITE_FAIL` | Any step | Cannot write memory.json | Log to error.log only; continue run; raise P3 Jira |
| `SNAPSHOT_CORRUPT` | Run start | memory.json state.status_snapshot unparseable | Reset snapshot to `{}`; treat as first run; raise P3 Jira |

---

## 11. Execution Checklist

The full 15-minute run loop with memory and error log writes called out explicitly:

```
RUN START
[ ] Generate run_id (e.g. run_042)
[ ] Write to memory.json: add run_history entry { run_id, run_start, run_status: "running" }
[ ] Read memory.json → state.status_snapshot (previous snapshot)
[ ] Read Logs/error.log → last 20 entries (pre-run check for known errors)

STEP 1 — Browser Login & Scrape (scrape_contract_statuses.py)
[ ] Pre-run check: scan error.log for past LOGIN_FAIL / TIMEOUT / SCRAPE_EMPTY entries → apply known fixes
[ ] Launch Playwright Chromium browser (headless=PLAYWRIGHT_HEADLESS, viewport 1280×800)
[ ] page.goto(SF_PORTAL_URL, wait_until="domcontentloaded")
[ ] Fill username + password → click "Log in" → wait_for_url change → wait for nav menu
    → On LOGIN_FAIL: write to error.log → raise P1 Jira → HALT entire run
    → On PORTAL_REDIRECT (SSO/MFA): write to error.log → raise P1 Jira → HALT entire run
[ ] page.goto(CONTRACTS_URL, wait_until="domcontentloaded") → wait for table tbody tr
    → On TIMEOUT / ELEMENT_NOT_FOUND: write to error.log → retry once → P2 Jira if still failing
[ ] Check aria-sort on Created Date th → if not "descending": scroll to top → click th a → verify sort
[ ] Infinite scroll loop: scroll last row into view → wait 2s → check row count growth
    → With descending sort: early-stop when record age > 14 days (usually ~7 scrolls, ~350 records)
    → On SCROLL_STALL: log records scraped so far; continue with partial data; raise P3 Jira
    → On SCRAPE_EMPTY (0 contracts in 14 days): check sort direction first; raise P2 Jira if confirmed empty
[ ] Close browser
[ ] Write to memory.json: step { "step": "browser_scrape", contracts_fetched, status, timestamp }
[ ] Update memory.json: last_action = "Scraped <N> contracts from Salesforce portal"

STEP 3 — Snapshot Comparison
[ ] Build new_snapshot dict from query results
[ ] Compare new_snapshot vs status_snapshot → identify changed contracts
[ ] Write to memory.json: step { "step": "compare_snapshot", contracts_changed, status, timestamp }
[ ] Update memory.json: last_action = "Identified <N> status changes"

STEP 4 — Excel Update
[ ] Pre-run check: scan error.log for past PA_4XX / PA_500 entries → apply fixes if found
[ ] POST contract list to Power Automate Excel-update flow via update_excel_via_pa.py
    → On error: write to error.log → check known_issues → retry or raise Jira
    → Do NOT proceed to Teams notifications if this step fails
[ ] Write to memory.json: step { "step": "excel_update", excel_updated: true/false, status, timestamp }
[ ] Update memory.json: last_action = "Excel updated via Power Automate"

STEP 5 — Teams Notifications (for each changed contract)
[ ] For each contract in changed list:
    [ ] Pre-run check: scan error.log for past TEAMS_NOTIFY_FAIL entries
    [ ] POST change payload to Teams-notify flow via notify_teams_via_pa.py
        → On error: write to error.log → retry once → P3 Jira if still failing
    [ ] Write to memory.json: step { "step": "teams_notify", contract_no, status, timestamp }
[ ] Update memory.json: teams_notified = <count>, last_action = "Teams notified for <N> contracts"

STEP 6 — Snapshot Save
[ ] Overwrite memory.json → state.status_snapshot with new_snapshot
[ ] Write to memory.json: step { "step": "snapshot_save", status, timestamp }

RUN END
[ ] Update memory.json run_history entry: { run_end, run_status: "success/partial/failed",
    contracts_fetched, contracts_changed, excel_updated, teams_notified }
[ ] Update memory.json: last_run = <ISO timestamp>, last_action = "Run complete"
```

---

## 12. Data Safety Rules

- Never overwrite `status_snapshot` in memory until the Excel update POST has succeeded (Steps 4 and 6 are intentionally ordered).
- If the Excel update fails, do **not** send Teams notifications — state and notifications must stay in sync.
- `DRY_RUN = True` flag at the top of every tool skips all POST calls and prints payloads to console instead. Memory and error.log writes still happen in dry-run mode so the run is fully traceable.
- `error.log` is **append-only** — existing entries are never deleted or overwritten. In-place resolution updates are written as a new NDJSON line referencing the original `run_id` and `timestamp`.

### 12.1 Cloud Run State Safety

Cloud Run containers are stateless. Files written inside the container can disappear on cold start, redeploy, scale-to-zero, or new instance creation.

Before enabling 15-minute production scheduling:

- Configure `GCS_MEMORY_BUCKET` and `GCS_MEMORY_BLOB` in Cloud Run.
- Initial memory JSON has been uploaded to `gs://ai-for-jswone-contract-agent-state/contract-status-agent/memory.json`.
- Cloud Run service account `729173585258-compute@developer.gserviceaccount.com` has been granted access to the bucket.
- Keep Cloud Run concurrency at `1` until a locking/versioning strategy is added.
- Avoid relying on `Tools/last_scraped_contracts.json` in production; it is a local debug artifact only.

Planned GCS variables:

| Variable | Purpose |
|----------|---------|
| `GCS_MEMORY_BUCKET` | Bucket that stores the persisted memory JSON |
| `GCS_MEMORY_BLOB` | Object path, e.g. `contract-status-agent/memory.json` |

`memory_store.py` is the adapter. If `GCS_MEMORY_BUCKET` is unset, local runs continue to use `Memory/memory.json`. If it is set, Cloud Run reads and writes memory in GCS.
