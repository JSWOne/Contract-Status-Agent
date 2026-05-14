# ContractLoggingAgent - Skill Instructions
> **Parent Orchestrator:** ContractSOAgent  
> Version: 3.0.0 | Phase: 2 | Status: FULLY DEPLOYED ON GCP — Background thread card posting, self-learning pre-check, PA concurrency+timeout fixes live | Last Updated: 2026-05-08

---

## 1. Objective

Create new contracts in the JSW Steel Community Salesforce portal after a user confirms the required contract details from Microsoft Teams.

The current build covers the full intended journey:

1. User enters the Jira `O360` ticket number in the **Contract logging** Teams channel.
2. Bot fetches / prepares the contract details and posts an Adaptive Card for confirmation.
3. User clicks **Confirm**.
4. Confirmed details are posted back into Teams for audit history.
5. Agent logs into the JSW Steel Community Salesforce portal.
6. Agent opens the New Contract wizard, fills confirmed parameters, saves the contract, and extracts the generated Contract Number.
7. Agent closes the browser after successful Contract Number extraction.
8. Agent posts a Teams success card with the generated Contract Number.

---

## 2. Trigger Flow

| Step | Actor | Action |
|------|-------|--------|
| 1 | User | Enters an `O360` Jira ticket number in the Teams **Contract logging** channel |
| 2 | Bot / Workflow | Replies that contract creation processing has started for that ticket |
| 3 | Bot / Workflow | Reads or prepares contract details from the Jira ticket |
| 4 | Bot / Workflow | Posts an Adaptive Card with the extracted contract parameters |
| 5 | User | Reviews the Adaptive Card and clicks **Confirm** |
| 6 | Bot / Workflow | Posts the confirmed details back into Teams for audit purposes |
| 7 | Python Agent | Logs into JSW Steel Community Salesforce portal |
| 8 | Python Agent | Opens New Contract wizard, fills confirmed values, saves, and extracts generated Contract Number |
| 9 | Python Agent | Closes browser after successful Contract Number extraction |
| 10 | Python Agent / Workflow | Posts Teams success card with generated Contract Number |

---

## 3. Teams Confirmation Card

The Adaptive Card should show the key contract creation parameters before the portal automation starts.

Expected fields:

| Field | Example |
|-------|---------|
| Jira Ticket | `O360-15342` |
| Contract Type | `ZCQT` |
| Contract Source | `Standard` |
| Sold To Party | `40039807` |
| Ship To Party | `40111475` |
| Payer | `40102336` |
| Division | `HRC` |
| Distribution Channel | `OEM` |
| PO Number | `Test PO 24 Apr 2026` |
| PO Date | `24/04/2026` |
| Contract End Date | `23/07/2026` |

The card must include a **Confirm** button.

---

## 4. Audit Logging In Teams

After the user clicks **Confirm**, the workflow must post the confirmed details in the Teams **Contract logging** channel.

This Teams post becomes the audit trail for:

- who confirmed the details
- which Jira ticket was used
- what values were confirmed
- when the confirmation happened

The audit post should be human-readable and include the same fields shown in the confirmation card.

---

## 5. JSW Steel Portal Login And Navigation

After confirmation, the Python agent will log into the JSW Steel portal and navigate to:

```text
https://jswsteel.my.site.com/jswone/s/recordlist/Contract/Default
```

Implementation rule:

Reuse the Playwright login and navigation pattern already built in:

```text
ContractSOAgent/Contract Status Agent/Tools/scrape_contract_statuses.py
```

The Contract Logging Agent should use the same portal-login approach as Contract Status Agent, then stop on the Contract list page for this phase.

Once the Contract list page is reached successfully, the agent must notify Teams with a message such as:

```text
Successfully logged into JSW Steel portal and navigated to the Contract page for <Jira Ticket>.
```

Credential handling:

- Do not hardcode portal credentials in code or markdown.
- Store credentials in local `.env` or Cloud Run environment variables.
- Use environment variables such as:

```text
JSW_PORTAL_USERNAME
JSW_PORTAL_PASSWORD
```

---

## 6. Reference Project Reviewed

Reference folder:

```text
C:\Users\2751342\OneDrive - JSW\Desktop\VS Code\SO Contract Agent
```

Useful existing Contract logging files reviewed:

| Reference File | What We Will Reuse / Adapt |
|----------------|----------------------------|
| `Contract logging/workflows/contract_creation.md` | Existing Teams -> Jira -> Adaptive Card -> Confirm flow design |
| `Contract logging/tools/webhook_listener.py` | Flask routes for Teams outgoing webhook, Power Automate confirmation callback, Adaptive Card building, Teams posting |
| `Contract logging/tools/fetch_jira_ticket.py` | Jira Cloud ticket fetch and custom field normalization |
| `Contract logging/tools/salesforce_login.py` | Playwright portal login and Contract page navigation patterns |
| `Contract logging/tools/extract_document_details.py` | Optional PO number / PO date extraction logic if Jira attachment extraction is needed later |

The new ContractSOAgent version should not blindly copy the old project. It should rebuild the required pieces cleanly under:

```text
ContractSOAgent/Contract Logging Agent/Tools/
```

---

## 7. Final Files / Tools Required For Phase 1

| File / Tool | Purpose | Build Status |
|-------------|---------|--------------|
| `Tools/webhook_listener.py` | Flask app for Teams ContractBot trigger, confirmation callback, health check, and background processing | Built |
| `Tools/fetch_jira_ticket.py` | Fetch `O360` Jira ticket details and normalize custom fields | Built |
| `Tools/build_contract_card.py` | Build the editable Adaptive Card with contract parameters and Confirm button | Built |
| `Tools/notify_teams.py` | Post Adaptive Cards / text messages to Teams through Power Automate webhook URLs | Built |
| `Tools/navigate_contract_page.py` | Playwright login into JSW Steel portal and navigate to Contract list page | Built |
| `Tools/run_contract_logging_agent.py` | Local one-shot runner for testing the Phase 1 flow without Teams webhook when needed | Built |
| `Tools/.env.example` | Document required environment variables without secrets | Built |
| `Tools/requirements.txt` | Python dependencies: Flask, requests, python-dotenv, playwright | Built |
| `main_contract_logging.py` | Cloud Run / gunicorn entrypoint for Contract Logging Agent | Built |
| `Dockerfile.contract-logging` | Cloud Run container definition for Contract Logging Agent | Built |
| `cloudbuild-contract-logging.yaml` | Optional Cloud Build deployment config for Contract Logging Agent | Built |
| `Memory/memory.json` | Tracks current design state, last action, pending items, and future run state | Required |
| `Logs/error.log` | Structured JSONL error / learning log similar to Contract Status Agent | Required |

Phase 2 contract creation tool:

| File / Tool | Purpose |
|-------------|---------|
| `Tools/create_contract_in_portal.py` | Fill the JSW Steel portal New Contract form, wait for save, and extract generated Contract Number |

This tool is now wired into:

| Caller | Behavior |
|--------|----------|
| `Tools/run_contract_logging_agent.py --create-contract` | Local test: fetch Jira details, open New Contract form, fill values, wait for Save, extract Contract Number |
| `POST /contract-confirm` in `Tools/webhook_listener.py` | Teams flow: after Confirm, post audit card, open/fill New Contract form, wait for Save, post Contract Number to Teams |

Current save behavior:

- The script fills the form and clicks **Save** automatically.
- Contract Start Date is left as the Salesforce portal default. Do not fill it from automation.
- Purchase Order Date is converted to Salesforce portal format such as `24-Apr-2026`.
- After Save, the script waits for the generated Contract detail page, extracts the Contract Number, closes the browser, and returns the result to Teams / CLI.

---

## 8. Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `JIRA_DOMAIN` | Jira Cloud domain, for example `jswone.atlassian.net` |
| `JIRA_EMAIL` | Jira API user email |
| `JIRA_API_TOKEN` | Jira API token |
| `TEAMS_CONTRACT_BOT_TOKEN` | Teams outgoing webhook HMAC token for ContractBot |
| `TEAMS_CONTRACT_LOG_WEBHOOK_URL` | Power Automate URL for posting cards/messages into Contract logging channel |
| `WEBHOOK_BASE_URL` | Public base URL of the Flask service |
| `JSW_PORTAL_USERNAME` | JSW Steel portal login username |
| `JSW_PORTAL_PASSWORD` | JSW Steel portal login password |

Secrets must stay in `.env`, Cloud Run environment variables, or Secret Manager. They must not be committed to git.

---

## 9. Local Flask Server Testing

Run this from the repo root:

```powershell
python "ContractSOAgent/Contract Logging Agent/Tools/webhook_listener.py"
```

The local Flask server exposes:

| Route | Purpose |
|-------|---------|
| `GET /` | Health check |
| `GET /health` | Health check |
| `POST /contract-webhook` | Teams outgoing webhook callback for `@ContractBot O360-xxxxx` |
| `POST /contract-confirm` | Power Automate callback after user clicks Confirm on Adaptive Card |

For Teams testing, `WEBHOOK_BASE_URL` must point to the public tunnel URL for the local Flask server.

Teams outgoing webhook callback:

```text
<WEBHOOK_BASE_URL>/contract-webhook
```

Power Automate HTTP callback after Adaptive Card response:

```text
<WEBHOOK_BASE_URL>/contract-confirm
```

---

## 10. Cloud Run Readiness

Contract Logging Agent has separate Cloud Run files so it does not overwrite the Contract Status Agent service:

| File | Purpose |
|------|---------|
| `main_contract_logging.py` | Imports and exposes Flask `app` from `Tools/webhook_listener.py` |
| `Dockerfile.contract-logging` | Builds a Playwright-ready container and runs `main_contract_logging:app` through gunicorn |
| `cloudbuild-contract-logging.yaml` | Cloud Build config to build, push, and deploy the `contract-logging-agent` image |

Cloud Run must receive all required secrets as environment variables or Secret Manager references.

Current deployed service:

| Item | Value |
|------|-------|
| Cloud Run service | `jsw-contract-logging-agent` |
| Region | `asia-south1` |
| Public URL | `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app` |
| Health endpoint | `GET /health` returns `OK` |
| Deployment type shown in Cloud Run | Container |
| Latest deployed revision | `jsw-contract-logging-agent-00028-n9h` |
| Image tag used | `asia-south1-docker.pkg.dev/ai-for-jswone/contract-agents/contract-logging-agent:35306cb1-9da4-4d94-a469-f3ce998abf1e` |
| Auto-deploy trigger | `jsw-contract-logging-agent-deploy` |
| Auto-deploy branch | `deploy-to-statusrepo` |
| Environment variables | Configured on Cloud Run service `jsw-contract-logging-agent` |

Production safety note:

- Existing Contract Status Agent service `jsw-contract-status-agent` was not redeployed.
- Status service stayed on revision `jsw-contract-status-agent-00041-22j`.
- Logging service uses separate Cloud Run service, separate Dockerfile, separate entrypoint, and separate Cloud Build trigger.

---

## 11. Current Build Status

The Contract Logging Agent now covers the full Contract creation journey:

| Item | Status |
|------|--------|
| Accept / detect Jira `O360` ticket number from Teams | Built |
| Send processing acknowledgement in Teams | Built |
| Fetch Jira details and prepare confirmation Adaptive Card | Built |
| Capture Confirm button response through `/contract-confirm` | Built |
| Post confirmed details back into Teams for audit | Built |
| Login into JSW Steel Community SF portal using Playwright | Built and locally tested |
| Create new Contract in portal | Built and locally tested |
| Click Save and extract generated Contract Number | Built and locally tested |
| Post created Contract Number to Teams | Built and locally tested through CLI `--post-to-teams` |
| Close browser after successful Contract Number extraction | Built |

Local validation completed for CLI and portal creation. Production Teams webhook + Power Automate Confirm callback validation is now complete.

---

## 12. Inputs

| Input | Source | Required |
|-------|--------|----------|
| Jira Ticket Number | Teams message | Yes |
| Confirmed Contract Details | Teams Adaptive Card response | Yes |
| Portal Username | Environment variable | Yes |
| Portal Password | Environment variable | Yes |

---

## 13. Outputs

| Output | Destination |
|--------|-------------|
| Processing acknowledgement | Teams channel |
| Confirmation Adaptive Card | Teams channel |
| Confirmed audit details | Teams channel |
| Successful Contract page navigation message | Teams channel |
| Portal login / navigation result | Logs and runtime output |
| Error details | `Logs/error.log` |

---

## 14. Deployment Status

Functional status before Cloud Run:

- Local portal automation created Contract Number `00173615` for `O360-15342`.
- Full local create-contract test with Teams posting created Contract Number `00173630`.
- Browser close behavior is fixed by accepting `/jswone/s/detail/<recordId>` after Save.
- Teams success-card posting is supported by the production `/contract-confirm` path and by local CLI when `--post-to-teams` is used.

Current Phase 2 selector note:

- The New Contract modal is a Salesforce Lightning wizard.
- Lookup fields should be targeted using component selectors such as `c-reusable-lookup[data-id="Sold To"] input`, `Ship To`, `Payer`, and `Division`.
- Picklists should use named Lightning buttons such as `Contract_Source__c` and `Distribution_Channel` where available.
- Label-only selectors are kept only as fallback because they did not fill the active modal reliably.

Current New Contract automation learnings:

- Sold To selection can auto-populate Ship To and Payer; clear those selected pills before applying the confirmed Ship To and Payer values.
- Division must be selected from the already visible list option, for example `HRC Division`; do not type/search `HRC` like a lookup.
- Distribution Channel is required before pressing `Next`; local tests can pass it with `--distribution-channel OEM`.
- Purchase Order Date must be entered in Salesforce portal format such as `24-Apr-2026`, not the Jira/card format `24/04/2026`.
- Contract Start Date should be left as the Salesforce portal default; the automation should not overwrite it.
- After filling the New Contract form, automation clicks `Save`, waits for the generated contract page, extracts the Contract Number, and posts a Teams success card saying the SO Contract was created successfully on JSW Steel Community SF portal.

Cloud Run deployment progress on 2026-05-06:

- Created Artifact Registry repository `contract-agents` in `asia-south1`.
- Created separate Cloud Build trigger `jsw-contract-logging-agent-deploy` on branch `deploy-to-statusrepo`.
- Initial deploy-through-Cloud-Build failed because service account `sa-cloudbuild@ai-for-jswone.iam.gserviceaccount.com` lacks Cloud Run permission `run.services.get`.
- Changed `cloudbuild-contract-logging.yaml` to build and push the image only.
- Built and pushed image successfully through Cloud Build.
- Manually deployed separate Cloud Run service `jsw-contract-logging-agent` using signed-in user `milind.kumar@jsw.in`.
- Verified `GET /health` returns `OK`.
- Admin granted `roles/run.developer` to `sa-cloudbuild@ai-for-jswone.iam.gserviceaccount.com`.
- Auto-deploy then failed on missing `iam.serviceaccounts.actAs` for runtime service account `729173585258-compute@developer.gserviceaccount.com`.
- Admin granted `roles/iam.serviceAccountUser` to `sa-cloudbuild@ai-for-jswone.iam.gserviceaccount.com`.
- Restored the Cloud Build deploy step in `cloudbuild-contract-logging.yaml`.
- Reran trigger `jsw-contract-logging-agent-deploy`; build, image push, and Cloud Run deploy completed successfully.
- New logging revision after successful auto-deploy: `jsw-contract-logging-agent-00002-rl8`.
- Verified `GET /health` returns `OK` after auto-deploy.
- Verified existing Contract Status Agent remained unchanged on revision `jsw-contract-status-agent-00041-22j`.
- Configured Cloud Run environment variables on `jsw-contract-logging-agent` from local Contract Logging `.env`.
- Forced `WEBHOOK_BASE_URL` to `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app`.
- Forced `PLAYWRIGHT_HEADLESS=True` for Cloud Run.
- New logging revision after env var update: `jsw-contract-logging-agent-00003-f6d`.
- Verified expected env var names are present without printing secret values.
- Deleted temporary env-vars file from `C:\tmp`.
- Verified `GET /health` returns `OK` after env var update.

Production readiness history and final rules:

- Teams outgoing webhook callback URL is `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app/contract-webhook`.
- Power Automate Confirm callback URL is `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app/contract-confirm`.
- First production Teams confirm test reached Teams response acknowledgement, but the channel audit card did not appear.
- Fix added: `/contract-confirm` now accepts common Power Automate response wrappers, posts the audit card before portal automation, and makes local memory/log writes non-blocking.
- Production confirmation-card post then failed in Power Automate at `Post adaptive card and wait for a response` with `MissingOrInvalidBotMessageRequest`.
- Fix added: audit/success/failure cards use Teams Flowbot-safe Adaptive Card version `1.2`.
- Confirmation card uses Teams Flowbot-safe Adaptive Card version `1.2`. Do not use Adaptive Card `1.3` required-input validation in this Power Automate flow because `Post adaptive card and wait for a response` can keep running without showing a visible usable card in Teams.
- After confirmed-details audit card, Power Automate posts the single progress message: `Creating Contract on JSW Steel Salesforce for <ticket>. I will post the Contract number card to this channel shortly.`
- Cloud Run no longer posts its own progress Adaptive Card, to avoid duplicate Teams messages.
- Production log check showed `/contract-confirm` was returning HTTP 200 quickly without reliable Playwright progress logs because contract creation was launched in a daemon background thread.
- Fix added: `/contract-confirm` now runs JSW Steel Salesforce contract creation synchronously before returning, so Cloud Run keeps CPU active and Logs Explorer shows the actual creation path.
- Added `[contract-create]` log milestones for login started, login completed, new contract form open, form fill, save, and generated Contract Number.
- Production headless test reached the New Contract wizard but failed on page 2 with missing PO Number/date fields and missing Save button.
- Fix added: after clicking `Next`, automation verifies the wizard advanced to the Purchase Order step, retries `Next` if needed, fills PO/date fields by walking from visible label text to the nearby input, and uses a JS Save-button fallback.
- If JSW Steel Salesforce contract creation fails, Cloud Run posts a Teams failure Adaptive Card: `Sorry, Not able to create new contract for <ticket> due to this error.` with the captured error reason.
- Teams failure card is intentionally short: `Sorry, Not able to create new contract for <ticket> due to this error.` with a status note to check Cloud Run logs.
- Cloud Run logs now show detailed field-by-field progress: filling/filled Contract Type, Sold To, Ship To, Payer, Division, Distribution Channel, Contract Source, Purchase Order No., Purchase Order Date, Contract End Date, and Save.
- Cloud Run browser now uses a fixed 1920x1080 viewport because headless Salesforce rendering can differ from the local visible browser and hide/change the New Contract modal/footer behavior.
- Confirmation/adaptive-card posting to Teams now retries Power Automate calls up to 4 times with backoff and `Connection: close`, because Cloud Run saw a transient `urllib3.exceptions.SSLError: EOF occurred in violation of protocol` while posting the card.
- Production Teams test completed successfully: Teams ticket message -> confirmation card -> Confirm -> JSW Steel Salesforce portal create/save -> generated Contract Number -> Teams success card.
- Keep future Contract Logging Agent changes on branch `deploy-to-statusrepo` until production Teams testing is complete.
- Optional hardening: move secrets from Cloud Run plain env vars into Secret Manager after the first production test.
- Confirmation-card delivery fix on 2026-05-07: `/contract-webhook` no longer starts `process_ticket` in a daemon background thread. It fetches Jira and posts the confirmation card while the request is active, then returns the same Teams acknowledgement. Cloud Run can throttle CPU after a response, so background Teams/Power Automate posting was unreliable and caused tickets to acknowledge without showing the Confirm card.
- **REVERSED on 2026-05-08:** `/contract-webhook` now uses a background daemon thread again for PA card posting (see Section 17). The card must appear AFTER the user's Teams message — returning synchronously before PA posts causes the card to appear before the user's message due to PA processing the trigger immediately. The fix: respond instantly, post card asynchronously. Cloud Run min-instances=1 keeps the container warm so the thread completes.

Final Playwright production rules saved on 2026-05-07:

- Keep Contract Status Agent and Contract Logging Agent independent. Do not change the status agent service, root Dockerfile, or root entrypoint for logging-agent work.
- `/contract-confirm` must run JSW Steel Salesforce contract creation synchronously, not in a daemon background thread, so Cloud Run keeps CPU active and logs the full Playwright journey.
- `/contract-webhook` uses a daemon background thread for PA card posting (reversed 2026-05-08 — see Section 17). `/contract-confirm` still runs Salesforce creation synchronously.
- Use fixed Chromium viewport `1920x1080` in Cloud Run because Salesforce Lightning rendered differently in headless mode with smaller/default sizing.
- Before filling, verify the New Contract wizard is really open by checking for `New Contract`, `Contract Type`, and `Sold To Party`.
- Sold To can auto-populate Ship To and Payer. Clear those selected pills before applying the confirmed Ship To and Payer values.
- Division is not a lookup search field. Select the already visible Division option such as `HRC Division`; do not type `HRC` into the search bar.
- Distribution Channel must be selected before clicking `Next`.
- Distribution Channel is required, but enforcement is server-side in `/contract-confirm`. If the user confirms with a blank value, the agent posts a short Teams validation message and stops before Salesforce automation.
- `/contract-confirm` validates Distribution Channel before audit posting or Salesforce automation. If it is blank, `-`, or the Teams bullet placeholder `•`, the agent posts a Teams validation message asking the user to fill Distribution Channel first and stops the run.
- The Salesforce creation function also validates Distribution Channel as a second safety net, so browser launch is blocked even if a future flow calls the creation function directly.
- After `Next`, verify the wizard advanced to the Purchase Order page. Retry `Next` if the page still shows first-step fields.
- PO Date and Contract End Date must be filled in portal format `DD-MMM-YYYY`, for example `24-Apr-2026`.
- Contract Start Date should be left as the portal default. Do not fill it from automation; only fill Purchase Order No., Purchase Order Date, and Contract End Date on the second page.
- For second-page fields, use the exact portal labels `Purchase Order No.`, `Purchase Order Date`, and `Contract End Date`. Earlier logs showed `observed=<blank>` because the diagnostic reader used weak label variants and container walking even when the portal screen actually displayed the filled values.
- Save handling must support both normal button selectors and the JavaScript fallback because the Save footer can be hard to locate in headless Salesforce.
- After Save, accept `/jswone/s/detail/<recordId>` URLs as successful contract detail navigation and extract the generated Contract Number from the page.
- Close the browser after successful Contract Number extraction.
- Teams should show only short human-readable status/failure cards. Detailed field-by-field diagnostics belong in Cloud Run logs.
- Cloud Run logs must keep field progress messages: filling/filled Contract Type, Sold To, Ship To, Payer, Division, Distribution Channel, Contract Source, Purchase Order No., Purchase Order Date, Contract End Date, and Save.
- The second-page helper now retries fill/read using the nearest visible control beside short exact labels only. Avoid broad ancestor/container walking because it caused misleading `observed=<blank>` diagnostics even when Salesforce displayed the field values.
- Teams/Power Automate posting must keep retry/backoff with `Connection: close` because production saw a transient `urllib3.exceptions.SSLError: EOF occurred in violation of protocol`.
- Contract Source is a Salesforce picklist, not a text input. If Contract Source is not selected, the wizard can stay on the first page and later PO/date fill logs become misleading. Do not fall back to normal input typing for Contract Source or Distribution Channel.
- After clicking `Next`, the automation must raise immediately if the Purchase Order step is not reached. It must not continue filling Purchase Order No., Purchase Order Date, or Contract End Date while the wizard is still on the first page.
- Added a DOM/coordinate combobox trigger fallback for Salesforce Lightning dropdowns near visible labels. This is specifically to handle headless Cloud Run cases where role/name selectors cannot open Contract Source or Distribution Channel.

Current live testing status on 2026-05-07:

- Latest pushed fix: `34abda6` - `fix: fail fast when contract wizard does not advance`.
- Latest deployed Contract Logging Agent revision: `jsw-contract-logging-agent-00021-6jn`.
- Health check after deploy returned `OK`.
- Existing Contract Status Agent was verified unchanged on revision `jsw-contract-status-agent-00041-22j`.
- Current activity: live Teams testing by entering multiple O360 ticket numbers in the `Contract logging` channel.
- The expected Teams journey for each test is: user posts O360 ticket -> outgoing webhook acknowledgement -> Jira details confirmation Adaptive Card -> user clicks Confirm -> Power Automate posts confirmed audit details -> Power Automate posts creating-contract progress message -> Cloud Run creates the contract in JSW Steel Salesforce -> Teams receives final Contract Number success card or short failure card.
- If a run fails during Salesforce creation, Teams should show only the short failure message, while Cloud Run logs should contain field-level details showing the last successful step.
- Important log checkpoint for the latest fix: before filling Purchase Order fields, logs should show `Contract Source` selected and the wizard should have reached the Purchase Order step. If not, the agent stops early instead of creating misleading PO/date errors.

---

## 15. Session 2026-05-07 — End-to-End Test Results and Bug Fixes

### Teams Test Results

| Ticket | Contract Type | Distribution Channel | Result | Contract Number |
|--------|--------------|----------------------|--------|----------------|
| O360-15705 | ZCQD | OEM | **Success** | `00174683` |
| O360-15707 | ZCQT | OEM | **Failed** | N/A — see bug below |

### Root Cause: ZCQT Wizard Navigation Failure

O360-15707 is contract type **ZCQT (JSW Dom Contract)**. After clicking Next on page 1, the Salesforce portal performs a slower server-side validation for ZCQT than for ZCQD. The previous `ensure_second_step` waited only 12 seconds and checked only text-based indicators — it never detected ZCQT's second step because:

1. The 12-second timeout was too short for ZCQT server validation.
2. The first Next click may not register if the portal is still processing.
3. The URL-change signal (most reliable detection method) was not being used.

### Fixes Applied (commit `da88df8`)

**`create_contract_in_portal.py` — `ensure_second_step`:**
- Added URL-change detection: if `page.url` changes from `jsw-one-new`, navigation is confirmed regardless of body text.
- Added `_STEP1_MARKER` check: if `Contract Type` disappears from body, page has moved past step 1.
- Retry Next click at 5 seconds and 10 seconds if page has not yet moved — handles ZCQT slow server validation.
- Total timeout extended to 20 seconds.

**`webhook_listener.py` — GCS-backed unified memory (commit `726adfd`, 2026-05-08):**
- Fixed `LOG_PATH` — previously wrote to `/app/Logs/error.log` (read-only in Cloud Run). Now uses `/tmp/error.log` when `GCS_MEMORY_BUCKET` is set.
- Added `GCS_MEMORY_BUCKET` env var (`ai-for-jswone-contract-agent-state`) to the `jsw-contract-logging-agent` Cloud Run service.
- **Unified into single GCS blob** `contract-logging-agent/memory.json` (eliminated separate `error_memory.json` which caused duplication). The memory.json now holds: `skill`, `last_run`, `last_action`, `state` (run_history, pending_items, completed_items), `known_issues`, `errors[]`, `successes[]`.
- `_read_gcs_memory()` / `_write_gcs_memory()` are the GCS adapters. `read_memory()` prefers GCS when `GCS_MEMORY_BUCKET` is set, falls back to local file.
- `write_memory_step()` persists to both local `memory.json` AND GCS after each step.
- `record_contract_error()` appends every failed creation; `record_contract_success()` appends successes and marks prior errors for the same ticket as resolved.
- Last 200 run_history entries, 200 errors, and 200 successes are retained; old entries trimmed automatically.

### Cloud Build Trigger Fix

Discovered that the logging agent Cloud Build trigger watches the `Contract-Status-Agent` GitHub repo (`statusrepo` remote), not the `Contract-SO-AI-Agent` repo (`origin` remote). The two remotes are:

| Remote | GitHub Repo | Purpose |
|--------|-------------|---------|
| `origin` | `JSWOne/Contract-SO-AI-Agent` | Local working copy / backup |
| `statusrepo` | `JSWOne/Contract-Status-Agent` | Source watched by Cloud Build triggers |

**Rule going forward: always push to `statusrepo/main` to trigger Cloud Build deployments.**

The logging agent files were also missing from `statusrepo/main` (they had only existed on `deploy-to-statusrepo` branch). Both files are now committed to `statusrepo/main` so Cloud Build `includedFiles` matching works correctly.

### Deployment After Fix

| Item | Value |
|------|-------|
| Build triggered | `f2225c2b` — `jsw-contract-logging-agent-deploy` |
| Target service | `jsw-contract-logging-agent` |
| Contract Status Agent | **Unchanged** — `jsw-contract-status-agent-00041-22j` |

---

## 16. Self-Learning Agent Vision

The goal is for the Contract Logging Agent to learn from its own failures over time, so it does not repeat the same errors across different ticket runs.

### What "learning" means here

When the agent fails to create a contract, the failure is recorded in a persistent GCS file with full context: ticket ID, contract type, distribution channel, error step, and error message. When the same contract type or combination causes a similar failure again, that pattern becomes visible across runs.

The learning loop is:

```
Run → Fail → Record error to GCS error_memory.json
             (timestamp, ticket, contract_type, distribution_channel, error, resolved: false)
             ↓
Run → Succeed (same ticket or same type) → Mark prior error as resolved: true
             ↓
Over time: error_memory.json contains a history of which contract types / channels
           cause issues, which ones succeed, and whether a fix resolved the pattern.
```

### Planned next steps for self-learning

1. **Read past errors before attempting creation** — Before starting the Salesforce wizard for a ticket, the agent reads `error_memory.json` and checks if the same contract type + distribution channel has unresolved prior failures. It can log a warning or adjust its retry strategy.

2. **Error classification** — Categorise errors into known classes (e.g. `wizard_navigation_timeout`, `combobox_not_found`, `save_failed`) so the agent can distinguish retry-able from configuration errors.

3. **Automatic resolution notes** — When a code fix resolves a previously recorded error pattern, the fix commit message should reference the error class so the GCS log can be annotated with the resolution.

4. **Admin summary card** — Periodically post a Teams card showing: how many contracts succeeded vs failed this week, which contract types are unreliable, and any unresolved error patterns still open.

5. **GCS memory location** — `gs://ai-for-jswone-contract-agent-state/contract-logging-agent/memory.json` (unified — replaces the old `error_memory.json` which was eliminated on 2026-05-08)

### Current GCS unified memory format

```json
{
  "skill": "Contract Logging Agent",
  "last_run": "<ISO timestamp>",
  "last_action": "<last step description>",
  "state": {
    "pending_items": [],
    "completed_items": [],
    "run_history": [
      {
        "step": "create_contract_in_portal",
        "status": "success",
        "detail": "Created contract 00174683 for O360-15705 on JSW Steel Community SF portal",
        "timestamp": "2026-05-07T13:44:00Z",
        "extra": { "ticket_id": "O360-15705", "contract_number": "00174683" }
      }
    ]
  },
  "known_issues": [],
  "errors": [
    {
      "timestamp": "2026-05-07T13:16:45Z",
      "ticket_id": "O360-15707",
      "contract_type": "ZCQT",
      "distribution_channel": "OEM",
      "division": "GL",
      "error_message": "New Contract wizard did not reach step 2 after Next...",
      "resolved": false
    }
  ],
  "successes": [
    {
      "timestamp": "2026-05-07T13:44:00Z",
      "ticket_id": "O360-15705",
      "contract_type": "ZCQD",
      "distribution_channel": "OEM",
      "division": "GL",
      "contract_number": "00174683"
    }
  ]
}
```

---

## 17. Session 2026-05-08 — PA Fixes, Self-Learning Pre-Check & Card Ordering Fix

### Changes Deployed (revision `jsw-contract-logging-agent-00028-n9h`)

#### 1. Self-Learning Pre-Check (`check_past_errors`)

Added `check_past_errors(ticket_id, data)` helper in `webhook_listener.py` (near `record_contract_error`). Called inside `create_contract_after_confirm()` just before `create_contract_in_portal()`.

- Reads GCS `memory.json`, filters `errors[]` for entries where `contract_type` and `distribution_channel` match the current ticket AND `resolved == False`.
- If unresolved prior failures found → logs `[self-learning] N unresolved prior error(s) for contract_type=X distribution_channel=Y — last: <message>` to Cloud Run logs.
- Does **not** block contract creation — warning only.
- Returns empty list on any GCS read error (safe fallback).

#### 2. Background Thread for Confirmation Card Posting

**Problem:** PA posted the adaptive card immediately after receiving our HTTP trigger. Since the webhook was calling PA synchronously (inside `process_ticket()`), the card appeared in Teams BEFORE the user's O360 message due to timestamp ordering.

**Fix:** `contract_webhook()` now spawns a background `threading.Thread` for `process_ticket()` and returns "Processing..." **instantly** (before Jira fetch). PA then posts the card after the webhook has responded — guaranteeing the card appears chronologically AFTER the user's message.

```python
def _bg():
    with app.app_context():
        process_ticket(ticket_id)
threading.Thread(target=_bg, daemon=True).start()
return jsonify({"type": "message", "text": "Processing contract creation for ..."})
```

**Rule:** `/contract-confirm` still runs Salesforce creation **synchronously** — only `/contract-webhook`'s card posting step is backgrounded.

**Rule:** PA's "Post adaptive card and wait for a response" has **no** "Message ID / reply-to-thread" parameter in the current PA Teams connector version — reply-in-thread is not feasible via PA. Cards are posted as new channel messages (below the user's message).

#### 3. Power Automate Flow Fixes (manual, no code change)

| Fix | Setting | Value |
|-----|---------|-------|
| Concurrency Control | Trigger → Settings → Concurrency Control | Limit ON, Degree = 10 |
| Action timeout | "Post adaptive card and wait for a response" → Settings → Action timeout | `PT1H` |

- **Concurrency = 10:** Multiple O360 tickets can be processed in parallel without PA queuing. Previous default (sequential) caused 9-minute card delays when a prior run was stuck waiting.
- **PT1H timeout:** Stuck runs (user never clicked Confirm) now auto-cancel after 1 hour instead of waiting indefinitely (previously up to 30 days).
- Old stuck runs were manually bulk-cancelled via PA Run history → "Cancel all flow runs".

---

## 18. HRC SKU Confirmation Flow - Safe Sidecar Path

Implementation status: added as a separate SKU confirmation path. Existing contract creation routes and Playwright contract creation logic are not changed.

New files:

| File | Purpose |
|------|---------|
| `Tools/hrc_master_lookup.py` | Calls the Power Automate HRC master helper flow through `HRC_MASTER_LOOKUP_URL` for `get_sku_choices` and `get_sku_details`. Normalizes BP/SP codes with leading zero support. |
| `Tools/contract_memory.py` | Reads/writes unified local or GCS memory, finds contract context by Contract Number, stores pending SKU choices, and stores final confirmed SKU details. |

New routes:

| Route | Purpose |
|-------|---------|
| `POST /sku-webhook` | Accepts a Teams message containing a Contract Number and posts the HRC SKU selection card. |
| `POST /sku-select-confirm` | Handles first-card confirmation for Material, SKU/Description, and Qty. Calls the HRC master lookup helper for detailed rows. |
| `POST /sku-row-confirm` | Handles the optional multiple-row choice card when more than one HRC master row matches. |
| `POST /sku-details-confirm` | Stores final confirmed HRC SKU details and posts a success card. This phase does not create Salesforce SKU lines. |

New card builders in `Tools/build_contract_card.py`:

| Function | Purpose |
|----------|---------|
| `build_hrc_sku_selection_card` | First card with Contract Number, Division, Material dropdown, SKU/Description dropdown, Qty, and Confirm. |
| `build_hrc_sku_row_choice_card` | Row-choice card when multiple HRC master rows match the selected Material/SKU. |
| `build_hrc_sku_details_card` | Second card with prefilled or blank HRC line details for user confirmation. |
| `build_hrc_sku_confirmed_card` | Final success card after confirmed SKU details are stored in memory. |
| `build_hrc_sku_validation_failed_card` | Short Teams validation/error message for missing context or fields. |

Environment variables added to `.env.example`:

```text
HRC_MASTER_LOOKUP_URL=
TEAMS_SKU_LOG_WEBHOOK_URL=
```

Current HRC SKU phase behavior:

1. User posts a created Contract Number in Teams.
2. The bot finds the matching contract in Contract Logging memory/GCS.
3. If no contract is found, a short Teams message is posted.
4. If the contract division is not `HRC`, a short Teams message says only HRC is enabled for now.
5. The bot calls Power Automate helper action `get_sku_choices`.
6. User selects Material, SKU/Description, enters Qty, and confirms.
7. The bot validates Material, SKU/Description, and Qty.
8. The bot calls Power Automate helper action `get_sku_details`.
9. If multiple master rows match, the bot asks the user to pick the correct row.
10. If no row matches, the second card is shown blank for manual entry.
11. User confirms final HRC SKU details.
12. The confirmed SKU details are stored in memory and Teams receives: `SKU details confirmed successfully for contract <contract_number>.`

Safety rule:

- This phase stops at SKU details confirmation only. It does not call `salesforce_add_contract_line.py` and does not create Salesforce SKU lines yet.
- Existing `/contract-webhook`, `/contract-confirm`, and `create_contract_in_portal.py` behavior must remain untouched.


- `/contract-webhook` returns instantly via background thread; card is posted by PA after the response — card always appears after the user's message in the channel.
- PA concurrency must be set to ≥ 10 to prevent card delivery delays.
- PT1H timeout prevents accumulation of stuck PA runs that clutter the channel with old Confirm cards.
- Old stuck PA runs must be cancelled manually if they accumulate (or will auto-expire after 1 hour with PT1H set).

---

## 19. Session 2026-05-11 - HRC SKU Flow Deployment to Cloud Run

### Deployment Completed

The HRC SKU confirmation flow was deployed to the existing Contract Logging Cloud Run service without pushing to `main` and without touching the Contract Status Agent production service.

Deployment details:

| Item | Value |
|------|-------|
| Local branch | `deploy-zcqt-fix` |
| Commit | `5007977 feat: add HRC SKU confirmation flow` |
| Pushed branch | `statusrepo/deploy-to-statusrepo` |
| Trigger used | `jsw-contract-logging-agent-deploy` |
| Trigger file | `cloudbuild-contract-logging.yaml` |
| Build ID | `743b5f6a-59cd-4c0f-b191-449ab1017137` |
| Build status | `SUCCESS` |
| Logging service revision | `jsw-contract-logging-agent-00030-p6w` |
| Logging service URL | `https://jsw-contract-logging-agent-blajkpcmsa-el.a.run.app` |
| Health check | `/health` returned `OK` |

Important safety note:

- Code was pushed only to `deploy-to-statusrepo`.
- The `main` branch was not pushed.
- The Contract Status Agent Cloud Run service was not redeployed.
- Contract Status Agent remained on revision `jsw-contract-status-agent-00044-gs2` during this deployment.

### Cloud Run Environment Status

Configured/present on Cloud Run:

| Env Var | Status |
|---------|--------|
| `TEAMS_SKU_LOG_WEBHOOK_URL` | Added to Contract Logging Cloud Run revision `00030-p6w` |
| `GCS_MEMORY_BUCKET` | Already present |
| Contract creation env vars | Already present |

Still pending:

| Env Var | Reason |
|---------|--------|
| `HRC_MASTER_LOOKUP_URL` | Required for the HRC SKU flow to fetch Material, SKU/Description, and detailed row data from the Excel master through Power Automate. |

Until `HRC_MASTER_LOOKUP_URL` is configured, the deployed service can run and remain healthy, but the HRC SKU card flow cannot load SKU choices from the master file.

### HRC SKU Flow Testing Plan on Teams

Use this after the Power Automate helper flow for HRC master lookup is ready and its URL is configured as `HRC_MASTER_LOOKUP_URL`.

1. Confirm the logging service is live:

```powershell
Invoke-RestMethod "https://jsw-contract-logging-agent-blajkpcmsa-el.a.run.app/health"
```

Expected output:

```text
OK
```

2. In Teams, go to:

```text
SO Contract Agent -> Contract logging
```

3. Post a contract number that already exists in Contract Logging memory and was created through this bot, for example:

```text
00174683
```

4. Expected behavior:

- Bot finds the contract in memory/GCS.
- Bot confirms the division is `HRC`.
- Bot calls `HRC_MASTER_LOOKUP_URL` with action `get_sku_choices`.
- Teams receives the first HRC SKU adaptive card.

5. First card should show:

| Field | Expected |
|-------|----------|
| Contract Number | Prefilled/read-only |
| Division | Prefilled/read-only as `HRC` |
| Material | Dropdown from HRC master lookup |
| SKU/Description | Dropdown from HRC master lookup |
| Qty | User input |
| Confirm | Button |

6. Select Material, SKU/Description, enter Qty, then click Confirm.

7. Expected second step:

- Bot validates Material, SKU/Description, and Qty.
- Bot calls `HRC_MASTER_LOOKUP_URL` with action `get_sku_details`.
- If one row matches, Teams shows the second prefilled details card.
- If multiple rows match, Teams shows the row-choice card.
- If no rows match, Teams shows a blank/manual details card.

8. Confirm the second card.

9. Expected final Teams message:

```text
SKU details confirmed successfully for contract <contract_number>.
```

10. Confirm memory was updated:

- `Memory/memory.json` locally during local tests, or
- GCS `memory.json` during Cloud Run tests.

The confirmed line details should appear under the SKU confirmation memory area.

### Negative Tests

Run these before enabling this for wider use:

| Test | Expected Result |
|------|-----------------|
| Post an unknown contract number | Teams posts a short "contract not found" message. |
| Post a non-HRC contract number | Teams posts that only HRC is enabled for now. |
| Click first Confirm without Material | Teams posts/fails with "Please fill Material". |
| Click first Confirm without SKU/Description | Teams posts/fails with "Please fill SKU/Description". |
| Click first Confirm without Qty | Teams posts/fails with "Please fill Qty". |
| Lookup returns multiple rows | Teams shows row-choice card. |
| Lookup returns no rows | Teams shows blank/manual second details card. |

### Pending Before Full HRC SKU Testing

1. Create/finish the Power Automate helper flow that reads the HRC master file from SharePoint/OneDrive.
2. Configure the helper flow URL on Cloud Run:

```text
HRC_MASTER_LOOKUP_URL=<Power Automate HTTP URL>
```

3. Run one Teams test using a known HRC contract from memory.
4. Verify Cloud Run logs show:

```text
POST /sku-webhook
POST /sku-select-confirm
POST /sku-details-confirm
```

5. Verify final confirmed SKU details are stored in memory/GCS.

### Current Scope Boundary

This deployment only confirms and stores HRC SKU details. It does not create Salesforce contract line items yet.

Salesforce SKU/line-item creation will be built in the next phase after the HRC SKU confirmation cards are stable.

## Latest Production Fix: Contract Source Default

Date: 11-May-2026

During production testing for `O360-15811`, Cloud Run logs again showed the known first-page issue:

- `filling Contract Source with Standard`
- `filled Contract Source; observed=<blank>`
- `New Contract wizard did not reach step 2 after Next`

This matches the earlier saved learning: `Contract Source` is a Salesforce picklist and the portal normally defaults it to `Standard`. Trying to open/fill it in headless Cloud Run can disturb the wizard state and prevent the first page from advancing.

Fix applied:

- If `contract_source` is `Standard`, the Playwright script now skips filling `Contract Source`.
- The script logs: `skipping Contract Source because Salesforce defaults it to Standard`.
- Non-Standard contract source values still use the picklist selection path.

Preserved rules:

- Do not touch Contract Status Agent production service.
- Do not change the Teams/Power Automate confirmation-card contract.
- Continue to validate/fill `Contract Type`, `Sold To`, `Ship To`, `Payer`, `Division`, and `Distribution Channel` before clicking `Next`.
- If the wizard does not reach the Purchase Order page after `Next`, stop early and check first-page picklists before debugging PO/date fields.

---

## 20. Current HRC Pilot Status - 2026-05-12

### What Is Working Now

The Contract Logging Agent is live on the separate Cloud Run service:

```text
jsw-contract-logging-agent
```

The existing Contract Status Agent production service is separate and must remain untouched.

Current HRC pilot scope:

1. User posts an `O360` ticket number in the Teams **Contract logging** channel.
2. Teams outgoing webhook calls `/contract-webhook`.
3. The agent fetches Jira details and posts the contract confirmation Adaptive Card through Power Automate.
4. User reviews/edits values and clicks **Confirm**.
5. Power Automate posts confirmed details into the channel for audit.
6. Power Automate posts the progress message:

```text
Creating Contract on JSW Steel Salesforce for <ticket>. I will post the Contract number card to this channel shortly.
```

7. Power Automate calls `/contract-confirm`.
8. Cloud Run runs the Playwright contract creation flow synchronously.
9. The browser logs into JSW Steel Community Salesforce, opens the New Contract wizard, fills values, saves, extracts the Contract Number, closes the browser, and posts the Contract Number card back to Teams.

### Latest Contract Creation Learnings

These rules must be preserved for the HRC pilot:

| Area | Current Rule |
|------|--------------|
| Browser viewport | Keep fixed Cloud Run browser viewport at `1920x1080`; smaller/default sizes can hide the wizard footer or make `Next` unreliable. |
| Contract Source | If value is `Standard`, do not touch the field. Salesforce defaults it to Standard and opening the picklist can block the wizard from moving to step 2. |
| Distribution Channel | Must be selected before `Next`. If missing/blank/bullet placeholder, stop before Salesforce and post a short Teams validation message. |
| Contract Start Date | Do not fill it. Leave Salesforce portal default. |
| Date format | Use Salesforce format such as `08-May-2026`, not `08/05/2026`. |
| Second page fields | Fill only `Purchase Order No.`, `Purchase Order Date`, and `Contract End Date`. |
| Error cards | Teams error card must stay short. Detailed diagnostics belong in Cloud Run logs and memory. |
| Cloud Run execution | `/contract-confirm` must run synchronously so Playwright keeps CPU and logs are visible. |

### Recent Production Result

The latest Cloud Run production run for `O360-15812` completed contract creation successfully and generated:

```text
00175457
```

Older failed Teams cards for the same ticket came from previous runs before the latest Playwright `Next`/viewport hardening.

### HRC SKU Confirmation Flow Added

The HRC SKU sidecar flow has been added without changing the contract creation route contract.

New endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/sku-webhook` | User posts a Contract Number to start SKU confirmation. |
| `/sku-select-confirm` | Handles Material, SKU/Description, and Qty confirmation. |
| `/sku-row-confirm` | Handles multiple matching HRC master rows. |
| `/sku-details-confirm` | Stores final confirmed SKU details and posts success. |

New helper modules:

| File | Purpose |
|------|---------|
| `Tools/hrc_master_lookup.py` | Calls Power Automate helper flow using `HRC_MASTER_LOOKUP_URL`. |
| `Tools/contract_memory.py` | Finds created contract context from memory/GCS and stores confirmed SKU details. |

Important boundary:

- HRC SKU flow currently confirms and stores SKU details only.
- It does not create Salesforce contract line items yet.
- `salesforce_add_contract_line.py` is not part of the active production flow yet.

### HRC SKU Flow Pending

Before full SKU pilot testing:

1. Confirm the Power Automate HRC master helper flow is ready.
2. Configure Cloud Run env var:

```text
HRC_MASTER_LOOKUP_URL=<Power Automate helper HTTP URL>
```

3. Test with a known HRC contract number already created by the bot.
4. Confirm Teams receives the first SKU card.
5. Confirm second details card works for:
   - one matching row
   - multiple matching rows
   - no matching row/manual entry
6. Confirm final SKU details are saved in GCS memory.

### Current Next Work

The HRC pilot is split into two streams:

| Stream | Status |
|--------|--------|
| HRC contract creation from `O360` ticket | Working, but continue monitoring live Teams runs for Salesforce timing/picklist issues. |
| HRC SKU confirmation after contract creation | Built/deployed as sidecar endpoints; waiting for HRC master helper flow URL and Teams testing. |

Do not expand to CRCA, GI, GL, TMT, or other divisions/products until the HRC contract creation and HRC SKU confirmation flow are stable.

---

## 21. Master Lookup Architecture Decision - 2026-05-12

Chosen approach:

Use one generic Power Automate master lookup API flow with separate product/division master files inside the shared master folder.

Recommended structure:

```text
Contract Master Folder
  HRC.xlsx
  CRCA.xlsx
  GI.xlsx
  ...
```

Power Automate flow:

```text
Contract SKU Master Lookup API
```

The bot sends:

```json
{
  "action": "get_sku_choices",
  "division": "HRC",
  "bp_code": "0040123977",
  "sp_code": "0040111475"
}
```

The Power Automate flow should route by `division`:

| Division/Product | PA behavior |
|------------------|-------------|
| `HRC` | Read only the HRC master file/table |
| `CRCA` | Future: read only the CRCA master file/table |
| `GI` | Future: read only the GI master file/table |
| Others | Return a controlled "not enabled yet" response until implemented |

Performance decision:

- Do not read every product master file in one run.
- Read only the selected product/division file based on the incoming `division`.
- Return only the filtered values needed by the bot, not all 100+ Excel columns.
- For the first SKU card, return only `materials` and `skus`.
- For the second details card, return only the matched row fields required for that material type.

Why this approach was selected:

- Only one Cloud Run environment variable is needed for lookup, currently `HRC_MASTER_LOOKUP_URL` and later reusable as a generic master lookup URL.
- Only one Power Automate HTTP endpoint is needed from the bot side.
- Each product can still keep its own Excel file and product-specific columns.
- HRC can be completed first without blocking future CRCA/GI/product work.
- Future product logic can be added branch by branch inside the lookup flow without changing the Teams bot contract.

Current implementation boundary:

- HRC is the only active product/division for the SKU confirmation pilot.
- Other product types are intentionally deferred.
- The SKU confirmation flow still ends at confirming and storing SKU details; Salesforce line-item creation is not active yet.

---

## 22. HRC Master Lookup URL Configured - 2026-05-12

Configured `HRC_MASTER_LOOKUP_URL` on Cloud Run service:

```text
jsw-contract-logging-agent
```

Deployment result:

| Item | Value |
|------|-------|
| Cloud Run revision | `jsw-contract-logging-agent-00042-bt9` |
| Traffic | 100% |
| Health check | `/health` returned `OK` |
| Secret handling | Power Automate URL was configured in Cloud Run env vars only; do not store the signed URL in repo docs. |

HRC SKU confirmation can now call the Power Automate master lookup API. Next validation should be a Teams test with a known HRC contract number from Contract Logging memory.

---

## 23. HRC SKU Card Posting Fix - 2026-05-12

Issue seen during Teams test:

- User posted contract `00175457`.
- Bot replied with the preparation message.
- SKU adaptive card did not appear.

Root causes found in Cloud Run logs:

1. `TEAMS_SKU_LOG_WEBHOOK_URL` was incomplete in Cloud Run; it was missing the signed `sp`, `sv`, and `sig` query parameters, causing `401 Unauthorized`.
2. `HRC_MASTER_LOOKUP_URL` was configured correctly, but the Power Automate lookup flow returned `202` with an empty body and later `502 Bad Gateway`; the bot expected JSON and failed before posting the card.
3. The SKU webhook used a background thread after returning the Teams acknowledgement. Cloud Run needed CPU outside request handling so the background post could finish reliably.

Fixes applied:

| Fix | Result |
|-----|--------|
| Reconfigured full `TEAMS_SKU_LOG_WEBHOOK_URL` in Cloud Run | Signed SKU card-post URL now has `sp`, `sv`, and `sig` |
| Added fallback handling in `Tools/hrc_master_lookup.py` | Empty/non-JSON/failed lookup responses now return empty `materials`, `skus`, and `rows` instead of crashing |
| Enabled Cloud Run `--no-cpu-throttling` | Background SKU card worker can continue after Teams acknowledgement |

Deployment result:

| Item | Value |
|------|-------|
| Commit | `bf6ffcd fix: fallback when hrc lookup api is unavailable` |
| Cloud Run revision | `jsw-contract-logging-agent-00046-nvg` |
| Health check | `/health` returned `OK` |
| CPU throttling | `false` |
| Signed URL env check | `TEAMS_SKU_LOG_WEBHOOK_URL` and `HRC_MASTER_LOOKUP_URL` both present with `sig` |

Verification:

- Sent a signed `/sku-webhook` test for contract `00175457`.
- Cloud Run returned `200`.
- GCS memory recorded:

```text
Posted HRC SKU selection card for contract 00175457
```

Timestamp:

```text
2026-05-12T11:00:33Z
```

Current behavior:

- If the HRC master lookup Power Automate flow is unavailable, the first SKU card still posts.
- It uses fallback HRC material choices and manual SKU/Description entry.
- To get populated dropdowns from the Excel master, the HRC Master Lookup API flow still needs to return JSON instead of `202` empty or `502`.

---

## 24. HRC SKU Description Dropdown + Match Parameters - 2026-05-12

Updated the HRC SKU first card contract:

- Card now displays the master-match parameters:
  - `B P Code`
  - `S P Code`
  - `SHIP Plant Code`
- Bot now sends `ship_plant_code` to the HRC Master Lookup API along with `bp_code` and `sp_code`.
- For compatibility with Power Automate/Excel naming, the lookup request includes all three plant aliases:

```json
{
  "ship_plant_code": "1001",
  "ship_plant": "1001",
  "plant_code": "1001"
}
```

- SKU/Description now renders as an Adaptive Card dropdown when the lookup response returns descriptions in `skus`, `descriptions`, or `rows`.
- Lookup rows with uppercase Excel-style columns like `MATERIAL`, `DESCRIPTION`, and `SHIP PLANT` are supported.
- If existing contract memory does not include `ship_plant_code`, the SKU flow tries to fetch the Jira ticket again and enrich the context before calling the master lookup.

Expected HRC Master Lookup API behavior for `get_sku_choices`:

1. Filter the HRC file by `bp_code`, `sp_code`, and `ship_plant_code`.
2. Return JSON with material and description choices, for example:

```json
{
  "status": "success",
  "materials": ["S_HRCF", "S_HRCTLF"],
  "skus": [
    {
      "material": "S_HRCF",
      "description": "1.6X1060-P1-10748_2004-GR2"
    }
  ]
}
```

If the lookup API returns no JSON or fails, the card still posts using fallback material choices and manual description entry.

---

## 25. Latest HRC SKU Deployment State - 2026-05-12

Final update from the latest Teams/card testing session:

| Item | Value |
|------|-------|
| Latest deployed commit | `b274d5b fix: map jira plant name to hrc ship plant` |
| Latest Cloud Run revision | `jsw-contract-logging-agent-00048-lfn` |
| Service health | `/health` returned `OK` |
| CPU throttling | `false` |
| Test contract | `00175457` |
| Test ticket | `O360-15812` |
| Test result | SKU selection card posted successfully |

### What Was Fixed

The HRC SKU card needed to show and use all master-match parameters:

```text
B P Code
S P Code
SHIP Plant Code
```

The Jira ticket did not have a field literally named `Ship Plant Code`. For the tested HRC ticket, the plant value came from:

```text
Plant Name: 1001 - Vijayanagar Works
```

The bot now extracts:

```text
ship_plant_code = 1001
```

from Jira `Plant Name`.

### Current Card Behavior

The first HRC SKU card now displays:

| Field | Example from `00175457` |
|-------|--------------------------|
| Contract Number | `00175457` |
| Division | `HRC` |
| Jira Ticket | `O360-15812` |
| B P Code | `0040046287` |
| S P Code | `0040046287` |
| SHIP Plant Code | `1001` |

The bot sends the lookup request with:

```json
{
  "action": "get_sku_choices",
  "division": "HRC",
  "bp_code": "0040046287",
  "sp_code": "0040046287",
  "ship_plant_code": "1001",
  "ship_plant": "1001",
  "plant_code": "1001"
}
```

`ship_plant`, `plant_code`, and `ship_plant_code` are all sent for Power Automate compatibility.

### Description Dropdown Requirement

The `SKU / Description` field becomes a dropdown when the HRC Master Lookup API returns descriptions in any of these response keys:

```text
skus
descriptions
rows
```

Supported response examples:

```json
{
  "status": "success",
  "materials": ["S_HRCF"],
  "skus": [
    {
      "material": "S_HRCF",
      "description": "1.6X1060-P1-10748_2004-GR2"
    }
  ]
}
```

or:

```json
{
  "status": "success",
  "rows": [
    {
      "MATERIAL": "S_HRCF",
      "DESCRIPTION": "1.6X1060-P1-10748_2004-GR2",
      "SHIP PLANT": "1001"
    }
  ]
}
```

If Power Automate returns empty/non-JSON/`502`, the card still posts, but `SKU / Description` remains a manual text field.

### Verified Context

GCS memory verification after the latest signed `/sku-webhook` test:

```json
{
  "contract_number": "00175457",
  "ticket_id": "O360-15812",
  "division": "HRC",
  "distribution_channel": "OEM",
  "contract_type": "ZCQT",
  "sold_to_party": "0040046287",
  "ship_to_party": "0040046287",
  "payer": "40102336",
  "ship_plant_code": "1001"
}
```

Verification timestamp:

```text
2026-05-12T12:02:41Z
```

### Remaining Dependency

The bot side is ready for the description dropdown. The remaining dependency is the Power Automate `HRC Master Lookup API` response:

- It must filter the HRC Excel file by `bp_code`, `sp_code`, and `ship_plant_code`.
- It must return JSON with matched description values.
- Until it returns matching descriptions, the bot will keep posting the card with fallback/manual SKU description entry.

---

## 26. HRC SKU Dropdown and Second Card Progress - 2026-05-12

Latest Teams/Power Automate validation completed after the HRC Master Lookup API changes.

### First SKU Card - Working

The HRC first SKU card now posts and shows the required matching context:

| Field | Verified Value |
|-------|----------------|
| Contract Number | `00175457` |
| Jira Ticket | `O360-15812` |
| Division | `HRC` |
| B P Code | `0040046287` |
| S P Code | `0040046287` |
| SHIP Plant Code | `1001` |

Power Automate `get_sku_choices` was fixed by moving multi-condition Excel filtering out of `List rows present in a table` and into `Filter array`.

Direct lookup test for:

```json
{
  "action": "get_sku_choices",
  "division": "HRC",
  "bp_code": "0040046287",
  "sp_code": "0040046287",
  "ship_plant_code": "1001",
  "ship_plant": "1001",
  "plant_code": "1001"
}
```

returned:

```text
200 OK
```

with 5 SKU descriptions, including:

```text
10X2000X12000-P1-2062_2011-E350BR
12X2000X12000-P1-2062_2011-E350BR
10X2000X6100.-P1-2062_2011-E350BR
10X2000X6300.-P1-2062_2011-E350BR
12X2000X7000.-P1-2062_2011-E350BR
```

Result:

- `Material Type` dropdown is populated.
- `SKU / Description` dropdown is populated.
- Qty remains manually entered by the user.

### First Card Confirm - Working

The Teams Adaptive Card submit flow was wired so Power Automate forwards the card response to:

```text
POST /sku-select-confirm
```

The second card now appears after clicking **Confirm** on the first card.

Observed second card title:

```text
Confirm HRC SKU Details - Contract 00175457
```

Observed values:

| Field | Value |
|-------|-------|
| Material | `S_HRCTLF` |
| SKU | `10X2000X12000-P1-2062_2011-E350BR` |
| Qty | `10` |

### Current Gap on Second Card

The second card appears, but detailed fields are still blank/manual:

```text
Customer Order Category
Eq. Specification Group
Eq. Specification
Eq. Sub Specification
Width
Thickness
Length
Edge Condition
```

Reason:

- The bot can post the second card.
- The remaining Power Automate branch `get_sku_details` still needs to return full matched row details in `rows`.
- Current bot behavior falls back to blank/manual detail fields when `rows` is empty.

### Power Automate Work in Progress - `get_sku_details`

Inside `HRC Master Lookup API`, a second condition branch is being built:

```text
action = get_sku_details
```

Current progress:

1. Main condition checks:

```text
action = get_sku_choices
```

2. False branch now contains `Condition 1`.

3. `Condition 1` checks:

```text
action = get_sku_details
```

4. Inside `Condition 1 -> True`, added:

```text
List rows present in a table 1
Filter array 1
Select 1
```

5. `Filter array 1` should filter the full Excel rows by:

```text
B P CODE
S P CODE
SHIP PLANT
MATERIAL
DESCRIPTION
```

Expected advanced-mode filter:

```text
@and(
  equals(item()?['B P CODE'], triggerBody()?['bp_code']),
  equals(item()?['S P CODE'], triggerBody()?['sp_code']),
  equals(string(item()?['SHIP PLANT']), triggerBody()?['ship_plant_code']),
  equals(item()?['MATERIAL'], triggerBody()?['material']),
  equals(item()?['DESCRIPTION'], triggerBody()?['description'])
)
```

### Current Blocker

`Select 1` in the `get_sku_details` branch became invalid because Power Automate created the Select mapping as a JSON string instead of a JSON object.

Bad shape seen in Code view:

```json
"select": "{ ... }"
```

Required shape:

```json
"select": {
  "MATERIAL": "@item()?['MATERIAL']",
  "DESCRIPTION": "@item()?['DESCRIPTION']",
  "WIDTH": "@item()?['WIDTH']",
  "THICKNESS": "@item()?['THICKNESS']",
  "CUST ORDER": "@item()?['CUST ORDER']",
  "EqSpecifGrp": "@item()?['EqSpecifGrp']",
  "EqSpecifi": "@item()?['EqSpecifi']",
  "EqSub_Grade": "@item()?['EqSub_Grade']",
  "END_APPN": "@item()?['END_APPN']",
  "RH REQ": "@item()?['RH REQ']",
  "LENGTH": "@item()?['LENGTH']",
  "EDGE_CON": "@item()?['EDGE_CON']"
}
```

Recommended next action:

1. Delete the broken `Select 1`.
2. Recreate `Select 1` under `Filter array 1`.
3. Configure it from Code view so `select` is an object, not a string.
4. Add a `Response` action for this `get_sku_details` branch:

```json
{
  "status": "success",
  "rows": @{body('Select_1')}
}
```

Once `get_sku_details` returns a non-empty `rows` array, the second adaptive card will prefill the detailed HRC SKU fields automatically.

---

## 27. HRC SKU Details Card Prefill Working - 2026-05-14

Latest validation completed in Teams after fixing the Power Automate routing and `get_sku_details` branch.

### What Was Fixed

The Teams first-card Confirm was failing to produce the second card because the **AddSKUbot Teams Incoming Webhook** flow was still calling an old dev tunnel URL:

```text
https://pv2zsn2r-5000.inc1.devtunnels.ms/sku-confirm
```

That returned `NotFound`.

Correct URL configured:

```text
https://jsw-contract-logging-agent-729173585258.asia-south1.run.app/sku-select-confirm
```

Important endpoint distinction:

| Endpoint | Purpose |
|----------|---------|
| `/sku-select-confirm` | Handles first HRC SKU card Confirm and posts the second details card |
| `/sku-confirm` | Old/manual Salesforce line creation route; not used for this HRC confirmation flow |

### HRC Master Lookup API Status

The HRC Master Lookup API now supports:

| Action | Status | Result |
|--------|--------|--------|
| `get_sku_choices` | Working | Returns SKU descriptions for the first card dropdown |
| `get_sku_details` | Working | Returns matched HRC Excel row details for second card prefill |

Power Automate pattern used:

1. `List rows present in a table`
2. `Filter array` for multi-field matching
3. `Response` with matched rows

For `get_sku_details`, the flow filters by:

```text
B P CODE
S P CODE
SHIP PLANT
MATERIAL
DESCRIPTION
```

and returns:

```json
{
  "status": "success",
  "rows": [...]
}
```

### Verified Teams Result

The second adaptive card now appears and pre-fills values from the HRC Excel file.

Observed card:

```text
Confirm HRC SKU Details - Contract 00175457
```

Verified values:

| Field | Value |
|-------|-------|
| Material | `S_HRCTLF` |
| SKU | `10X2000X6100.-P1-2062_2011-E350BR` |
| Qty | `15` |
| Customer Order Category | `STD` |
| Eq. Specification Group | `BIS` |
| Eq. Specification | `2062_2011` |
| Eq. Sub Specification | `E350BR` |

This confirms the HRC Excel master lookup is now feeding the second card correctly.

### Current HRC Flow State

Working end-to-end up to SKU details confirmation:

1. User posts contract number in Teams.
2. Bot posts first HRC SKU selection card.
3. First card shows B P Code, S P Code, SHIP Plant Code.
4. Material and SKU/Description dropdowns are populated from HRC Excel.
5. User enters Qty and clicks Confirm.
6. Power Automate forwards response to `/sku-select-confirm`.
7. Bot calls HRC Master Lookup API with `get_sku_details`.
8. Bot posts second HRC SKU details card with HRC Excel fields prefilled.

### Next Phase

Next work is Salesforce contract line creation:

- Log into JSW Steel Salesforce portal.
- Search/open contract `00175457`.
- Start New Contract Line flow.
- Use confirmed HRC SKU details from Teams/GCS memory.
- Create the Salesforce line item.
- Return line item result card to Teams.

Important boundary:

- HRC SKU confirmation and detail prefill are now working.
- Salesforce line-item creation is the next phase and is not yet active in the main HRC confirmation flow.

### Follow-up UI Field Update - 2026-05-14

Added `Supply Plant / Depot` to the second HRC SKU details card.

Placement:

```text
RH REQ
Supply Plant / Depot
Customer Requested Date
```

Data source:

- The bot reads this value from the matched HRC lookup row using any of these aliases:

```text
SHIP PLANT
ship_plant
ship_plant_code
plant_code
Plant Code
```

Verified locally:

```text
Supply Plant / Depot = 1001
```

This field is included in the submitted SKU details payload as:

```text
plant_code
```

### Final Confirmation Progress Message - 2026-05-14

After the user clicks **Confirm SKU Details** on the second HRC card, the bot now posts a progress message instead of only saying the details were saved.

Message:

```text
Thanks for confirming. I am adding the SKU in contract <contract_number>. I will share the Contract Line Item shortly.
```

The card still includes the selected SKU facts:

```text
Material
SKU
Qty
```

This is a progress acknowledgement for the upcoming Salesforce line-item creation phase. The Salesforce line item is not yet created by this message until the Salesforce automation is wired into the final confirm route.
