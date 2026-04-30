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
