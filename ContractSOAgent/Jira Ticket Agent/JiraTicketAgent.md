# JiraTicketAgent — Skill Instructions
> **Parent Orchestrator:** ContractSOAgent
> Version: 1.0.0 | Phase: 5 | Status: 🔲 Pending | Last Updated: 2026-04-29

---

## 1. Objective

Create, update, and auto-close Jira tickets for tool failures, data exceptions, and manual review items raised by any sub-agent in the ContractSOAgent system. Acts as the central incident management layer.

---

## 2. Inputs

| Field | Source | Required |
|-------|--------|----------|
| Ticket Type | Calling skill | Yes (`Bug`, `Task`, `Story`) |
| Priority | Calling skill | Yes (`P1`, `P2`, `P3`, `P4`) |
| Summary | Calling skill | Yes |
| Description | Calling skill error log entry | Yes |
| Affected Skill | Calling skill | Yes |
| Affected Record ID | Calling skill | Optional |
| Error Log Entry | Logs/error.log of calling skill | Yes |

---

## 3. Outputs

| Output | Destination |
|--------|-------------|
| Jira Ticket ID | Returned to calling skill → logged in error.log ticket_id field |
| Ticket URL | Memory/memory.json → state.completed_items |
| Auto-close confirmation | Memory/memory.json on resolution |

---

## 4. Tools

| Script | Language | Purpose |
|--------|----------|---------|
| `create_ticket.py` | Python | Create a new Jira ticket via Jira REST API |
| `update_ticket.py` | Python | Update ticket status or add comment |
| `close_ticket.py` | Python | Transition ticket to Done when resolution confirmed |

---

## 5. Jira API Reference

| Parameter | Value |
|-----------|-------|
| Jira Base URL | *(To be configured — e.g., `https://jswoneplatforms.atlassian.net`)* |
| Auth Method | API Token (Basic Auth with email + token) |
| Project Key | *(To be defined — e.g., `CSOA`)* |
| Issue Types | `Bug`, `Task`, `Story` |
| Priority IDs | P1 = `Highest`, P2 = `High`, P3 = `Medium`, P4 = `Low` |
| Transition IDs | `To Do` → `In Progress` → `Done` |

---

## 6. Priority Logic

| Priority | Trigger Condition |
|----------|-------------------|
| **P1** | Data loss risk — record not created, existing record overwritten unexpectedly |
| **P2** | Logging failure — tool could not write to Salesforce after retry |
| **P3** | Status mismatch — Contract or SO stuck in unexpected state |
| **P4** | Warning — non-critical anomaly, informational alert |

---

## 7. Auto-close Logic

A ticket is eligible for auto-close when:
1. The calling skill writes a successful resolution to `Memory/memory.json → known_issues[]`
2. The next successful run of that skill confirms the record is now in the expected state
3. `close_ticket.py` transitions the Jira ticket to **Done** and logs the closure timestamp

---

## 8. Memory Schema (this skill)

```json
{
  "skill": "Jira Ticket Agent",
  "last_run": null,
  "last_action": null,
  "state": {
    "last_processed_id": null,
    "pending_items": [],
    "completed_items": []
  },
  "known_issues": []
}
```

---

## 9. Error Handling

| Error Code | Description | Auto-fix |
|------------|-------------|---------|
| `401` | Jira auth failed | Check API token config; alert operator |
| `400` | Bad request — missing required Jira field | Log locally, alert operator |
| `404` | Project/Issue Type not found | Check Jira project key config |
| `500` | Jira server error | Wait 30s, retry once; log locally if still failing |

---

## 10. Execution Checklist

```
[ ] Receive ticket creation request from calling skill
[ ] Read Memory/memory.json — check if a ticket already exists for this error
[ ] If existing open ticket found → update with new comment (avoid duplicates)
[ ] If no existing ticket → call create_ticket.py
[ ] Return ticket ID to calling skill
[ ] On resolution signal → call close_ticket.py
[ ] Update memory.json with ticket status
```

---

## 11. Implementation Status - 2026-05-15

Status: Initial Jira Ticket Agent implementation added.

Implemented tools:

- `Tools/jira_client.py` - shared Jira Cloud REST client, memory helper, error-log helper, priority mapping, and Atlassian document format conversion.
- `Tools/create_ticket.py` - creates a Jira issue or updates an existing open ticket when the same failure fingerprint is detected.
- `Tools/update_ticket.py` - adds comments to existing Jira tickets and updates memory state.
- `Tools/close_ticket.py` - transitions a Jira ticket to Done and moves it from pending to completed memory.
- `Tools/run_jira_ticket_agent.py` - CLI dispatcher for create, update, and close commands.
- `Tools/.env.example` - documents required Jira environment variables.
- `Tools/requirements.txt` - local requirements for the Jira tools.

Current behavior:

- Uses `JIRA_DOMAIN`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `JIRA_PROJECT_KEY`.
- Supports ticket types such as `Bug`, `Task`, and `Story`.
- Maps priorities as `P1 -> Highest`, `P2 -> High`, `P3 -> Medium`, and `P4 -> Low`.
- Deduplicates repeated failures using affected skill, affected record ID, summary, and error code.
- Stores open tickets in `Memory/memory.json -> state.pending_items`.
- Stores closed tickets in `Memory/memory.json -> state.completed_items`.
- Writes tool failures to `Logs/error.log`.

Verification:

- Python syntax check passed with:

```powershell
python -m compileall "ContractSOAgent/Jira Ticket Agent/Tools"
```

Pending:

- Configure real Jira values in `.env` or environment variables.
- Confirm the target Jira project key and available issue types.
- Run one real test ticket in Jira.
- Wire Contract Logging / Status agents to call Jira Ticket Agent on repeated failures.

### Cloud Run Deployment - 2026-05-15

Status: Deployed as a separate Cloud Run service.

Deployment details:

- Cloud Run service: `jsw-jira-ticket-agent`
- Region: `asia-south1`
- Latest revision: `jsw-jira-ticket-agent-00002-jqk`
- Service URL: `https://jsw-jira-ticket-agent-blajkpcmsa-el.a.run.app`
- Health endpoint verified:

```json
{
  "service": "jira-ticket-agent",
  "status": "ok"
}
```

Production safety check:

- Existing Contract Logging Agent remained unchanged on `jsw-contract-logging-agent-00058-c9v`.
- Existing Contract Status Agent remained unchanged on `jsw-contract-status-agent-00044-gs2`.
- Jira Ticket Agent was deployed through its own Cloud Build trigger: `jsw-jira-ticket-agent-deploy`.

Runtime configuration:

- Reused existing Jira values from the older local keys.
- `JIRA_DOMAIN=jswone.atlassian.net`
- `JIRA_EMAIL=milind.kumar@jsw.in`
- `JIRA_PROJECT_KEY=O360`
- `JIRA_DONE_TRANSITION_NAME=Done`
- `JIRA_API_TOKEN` configured on the Cloud Run service without printing the token.

Pending after deployment:

- Create one controlled real Jira test ticket through the new service.
- Add authentication/hardening if the endpoint will be exposed beyond internal Power Automate/service calls.
- Wire producer agents to call `POST /tickets` only after their retry/failure criteria are met.

### Cloud Run Smoke Test - 2026-05-15

Status: Passed.

Change made:

- O360 does not support Jira issue type `Task`.
- Added configurable issue-type mapping:
  - `Task -> Support`
  - `Story -> New Feature`
  - `Escalation -> Developer escalation`
  - `Bug -> Bug`

Deployment:

- Jira Ticket Agent redeployed successfully.
- Latest revision after environment update: `jsw-jira-ticket-agent-00004-575`
- Service URL remains: `https://jsw-jira-ticket-agent-blajkpcmsa-el.a.run.app`

Smoke test result:

```json
{
  "created": true,
  "ticket_id": "O360-16089",
  "ticket_url": "https://jswone.atlassian.net/browse/O360-16089"
}
```

Production safety check:

- Contract Logging Agent remained unchanged on `jsw-contract-logging-agent-00058-c9v`.
- Contract Status Agent remained unchanged on `jsw-contract-status-agent-00044-gs2`.

Next:

- Close/delete test ticket `O360-16089` if it is not needed.
- Wire Contract Logging / Status agents to call Jira Ticket Agent only for repeated/real failures.

### Jira Created Teams Endpoint - 2026-05-15

Status: Endpoint deployed, Teams webhook configuration pending.

Issue found:

- Jira Automation rule `Teams New Ticket Notifier` was still calling an old local dev tunnel:

```text
https://pv2zsn2r-5000.inc1.devtunnels.ms/jira-ticket-created
```

- That is why Jira Automation audit showed success but the Power Automate Teams flow had no new runs.

Fix added:

- Added Cloud Run route:

```text
POST /jira-ticket-created
```

- Jira Automation can now call:

```text
https://jsw-jira-ticket-agent-blajkpcmsa-el.a.run.app/jira-ticket-created
```

Deployment:

- Jira Ticket Agent redeployed successfully.
- Latest revision: `jsw-jira-ticket-agent-00005-vqc`
- Contract Logging Agent remained unchanged on `jsw-contract-logging-agent-00058-c9v`.
- Contract Status Agent remained unchanged on `jsw-contract-status-agent-00044-gs2`.

Route verification:

- Test request for `O360-16091` reached Cloud Run and normalized ticket details correctly.
- Teams post did not run yet because `JIRA_TEAMS_WEBHOOK_URL` is not configured on the Cloud Run service.

Pending:

- Copy the HTTP trigger URL from Power Automate flow `Jira Tickets Teams Incoming Webhook`.
- Set it on Cloud Run as `JIRA_TEAMS_WEBHOOK_URL`.
- Retest by creating a new Jira ticket or rerunning Jira Automation.

### Jira Teams Webhook Configuration - 2026-05-15

Status: Configured and tested.

Update:

- Set `JIRA_TEAMS_WEBHOOK_URL` on Cloud Run service `jsw-jira-ticket-agent` using the Power Automate flow `Jira Tickets Teams Incoming Webhook`.
- New Jira service revision after env update: `jsw-jira-ticket-agent-00006-mzw`.

Verification:

- Health check passed for `https://jsw-jira-ticket-agent-blajkpcmsa-el.a.run.app/`.
- Test POST to `/jira-ticket-created` for `O360-16091` returned:

```json
{
  "ok": true,
  "status_code": 202,
  "teams_posted": true
}
```

Notes:

- HTTP `202` means Power Automate accepted the Teams card request. Final visual delivery should be confirmed in the Teams `Jira Tickets` channel or Power Automate run history.
- Existing Contract Logging Agent remained unchanged on `jsw-contract-logging-agent-00058-c9v`.
- Existing Contract Status Agent remained unchanged on `jsw-contract-status-agent-00044-gs2`.
