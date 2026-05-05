# ContractLoggingAgent - Skill Instructions
> **Parent Orchestrator:** ContractSOAgent  
> Version: 1.2.0 | Phase: 1 | Status: Process design updated | Last Updated: 2026-05-05

---

## 1. Objective

Create new contracts in the JSW Steel portal after a user confirms the required contract details from Microsoft Teams.

The first build phase stops after:

1. User enters the Jira `O360` ticket number in the **Contract logging** Teams channel.
2. Bot fetches / prepares the contract details and posts an Adaptive Card for confirmation.
3. User clicks **Confirm**.
4. Confirmed details are posted back into Teams for audit history.
5. Agent logs into the JSW Steel portal and navigates to the Contract page.
6. Agent posts a Teams message confirming successful navigation to the Contract page.

Actual contract creation in the portal will be built in the next phase.

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
| 7 | Python Agent | Logs into JSW Steel portal and navigates to the Contract page |
| 8 | Python Agent / Workflow | Posts Teams message that Contract page navigation was successful |

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

- The script fills the form.
- It waits up to 10 minutes for the contract to be saved.
- For local testing, user can manually review and click **Save**.
- Fully automated Save can be added after the filled form is confirmed stable.

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
| `cloudbuild-contract-logging.yaml` | Optional Cloud Build config to build and deploy `contract-logging-agent` |

Cloud Run must receive all required secrets as environment variables or Secret Manager references.

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

Remaining local validation is the actual Teams webhook + Power Automate Confirm callback journey.

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

Remaining:

- Test the full Teams flow: Teams ticket message -> confirmation card -> Confirm -> portal create/save -> Teams success card.
- Push latest code to GitHub.
- Configure Cloud Run environment variables or Secret Manager references.
- Deploy Contract Logging Agent using `Dockerfile.contract-logging`.
- Update Teams outgoing webhook and Power Automate callback URLs to the Cloud Run service.
- Run one production Teams test after deployment.
