# SOStatusAgent — Skill Instructions
> **Parent Orchestrator:** ContractSOAgent
> Version: 1.0.0 | Phase: 4 | Status: 🔲 Pending | Last Updated: 2026-04-29

---

## 1. Objective

Poll Salesforce for the live status of **Order (SO)** records and report back. Triggered after a successful SO logging event or on a scheduled cron basis. Flags stale, unexpected, or missing statuses to the Jira Ticket Agent.

---

## 2. Inputs

| Field | Source | Required |
|-------|--------|----------|
| Salesforce Order Record ID(s) | Memory/memory.json → state.completed_items | Yes |
| Expected Status | Orchestrator / config | Optional |

---

## 3. Outputs

| Output | Destination |
|--------|-------------|
| Status report (per Order ID) | Console / n8n response / operator |
| Stale/mismatched status alert | Jira Ticket Agent (P3 ticket) |
| Updated status snapshot | Memory/memory.json |

---

## 4. Tools

| Script | Language | Purpose |
|--------|----------|---------|
| `check_so_status.py` | Python | Query Salesforce for Order status via SOQL |
| `refresh_token.py` | Python | Utility — refresh OAuth2 bearer token |

---

## 5. Salesforce API Reference

- **Object:** `Order`
- **Query Endpoint:** `/services/data/v59.0/query/?q=SELECT Id, Status, EffectiveDate, TotalAmount FROM Order WHERE Id IN (...)`
- **Status Field:** `Status` (standard picklist: `Draft`, `Activated`, `Cancelled`, etc.)

---

## 6. Memory Schema (this skill)

```json
{
  "skill": "SO Status Agent",
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

## 7. Error Handling

| Error Code | Description | Auto-fix |
|------------|-------------|---------|
| `401` | OAuth token expired | Invoke `refresh_token.py`, retry once |
| `404` | Order ID not found in Salesforce | Log P2 Jira ticket — possible logging failure |
| `STALE_STATUS` | Status unchanged beyond expected window | Log P3 Jira ticket |
| `500` | Salesforce server error | Wait 30s, retry once |

---

## 8. Execution Checklist

```
[ ] Read Memory/memory.json — get list of Order IDs to check
[ ] Build SOQL query for batch status fetch
[ ] For each Order:
    [ ] Compare returned Status against expected
    [ ] If mismatch or stale → flag to Jira Ticket Agent
    [ ] On success → update memory.json with current status snapshot
[ ] Write final state back to memory.json
```
