# ContractLoggingAgent - Skill Instructions
> **Parent Orchestrator:** ContractSOAgent  
> Version: 1.5.0 | Phase: 2 | Status: Cloud Run env vars configured; production Teams callback pending | Last Updated: 2026-05-06

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
- Contract Start Date is always set to today's date because the portal rejects past dates.
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
| Latest deployed revision | `jsw-contract-logging-agent-00003-f6d` |
| Image tag used | `asia-south1-docker.pkg.dev/ai-for-jswone/contract-agents/contract-logging-agent:35306cb1-9da4-4d94-a469-f3ce998abf1e` |
| Auto-deploy trigger | `jsw-contract-logging-agent-deploy` |
| Auto-deploy branch | `deploy-to-statusrepo` |
| Environment variables | Configured on Cloud Run revision `jsw-contract-logging-agent-00003-f6d` |

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

Local validation completed for CLI and portal creation. Remaining validation is production Teams webhook + Power Automate Confirm callback against Cloud Run.

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
- Contract Start Date must always be today's date because the portal rejects past start dates.
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

Pending for production readiness:

- Update Teams outgoing webhook callback URL to `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app/contract-webhook`.
- Update Power Automate Confirm callback URL to `https://jsw-contract-logging-agent-729173585258.asia-south1.run.app/contract-confirm`.
- First production Teams confirm test reached Teams response acknowledgement, but the channel audit card did not appear.
- Fix added: `/contract-confirm` now accepts common Power Automate response wrappers, posts the audit card before portal automation, and makes local memory/log writes non-blocking.
- Production confirmation-card post then failed in Power Automate at `Post adaptive card and wait for a response` with `MissingOrInvalidBotMessageRequest`.
- Fix added: confirmation/audit/success cards now use Teams Flowbot-safe Adaptive Card version `1.2`; removed newer `isRequired`, `errorMessage`, and action `style` properties from the confirmation card.
- After confirmed-details audit card, Power Automate posts the single progress message: `Creating Contract on JSW Steel Salesforce for <ticket>. I will post the Contract number card to this channel shortly.`
- Cloud Run no longer posts its own progress Adaptive Card, to avoid duplicate Teams messages.
- Production log check showed `/contract-confirm` was returning HTTP 200 quickly without reliable Playwright progress logs because contract creation was launched in a daemon background thread.
- Fix added: `/contract-confirm` now runs JSW Steel Salesforce contract creation synchronously before returning, so Cloud Run keeps CPU active and Logs Explorer shows the actual creation path.
- Added `[contract-create]` log milestones for login started, login completed, new contract form open, form fill, save, and generated Contract Number.
- Production headless test reached the New Contract wizard but failed on page 2 with missing PO Number/date fields and missing Save button.
- Fix added: after clicking `Next`, automation verifies the wizard advanced to the Purchase Order step, retries `Next` if needed, fills PO/date fields by walking from visible label text to the nearby input, and uses a JS Save-button fallback.
- If JSW Steel Salesforce contract creation fails, Cloud Run posts a Teams failure Adaptive Card: `Sorry, Not able to create new contract for <ticket> due to this error.` with the captured error reason.
- Failure diagnostics now include Cloud Run field-state details such as expected values, observed page values, current URL/title, visible buttons, and a body hint when Save or form-fill fails.
- Run one production Teams test: Teams ticket message -> confirmation card -> Confirm -> portal create/save -> Teams success card.
- Keep future Contract Logging Agent changes on branch `deploy-to-statusrepo` until production Teams testing is complete.
- Optional hardening: move secrets from Cloud Run plain env vars into Secret Manager after the first production test.
