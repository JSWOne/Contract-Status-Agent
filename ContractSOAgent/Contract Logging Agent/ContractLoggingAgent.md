# ContractLoggingAgent — Skill Instructions
> **Parent Orchestrator:** ContractSOAgent
> Version: 1.0.0 | Phase: 1 | Status: 🔲 Pending | Last Updated: 2026-04-29

---

## 1. Objective

Fetch new Contract records from upstream sources (API, Excel, n8n webhook) and create or update corresponding **Contract** objects in the JSW One Platforms Salesforce org.

Ensures idempotency: if a Contract already exists for a given source ID, the tool updates it rather than creating a duplicate.

---

## 2. Inputs

| Field | Source | Required |
|-------|--------|----------|
| Contract Number | Upstream API / Excel | Yes |
| Account Name / ID | Upstream API / Excel | Yes |
| Start Date | Upstream API / Excel | Yes |
| End Date | Upstream API / Excel | Yes |
| Contract Value | Upstream API / Excel | Yes |
| Status | Upstream API / Excel | Yes |
| Source Record ID | Upstream system | Yes (used for idempotency) |

---

## 3. Outputs

| Output | Destination |
|--------|-------------|
| Salesforce Contract Record ID | Memory/memory.json → state.completed_items |
| Error details (on failure) | Logs/error.log |
| Jira ticket ID (on failure) | Logs/error.log → ticket_id |

---

## 4. Tools

| Script | Language | Purpose |
|--------|----------|---------|
| `log_contract.py` | Python | Main tool — fetch source data, upsert Contract in Salesforce |
| `refresh_token.py` | Python | Utility — refresh OAuth2 bearer token |

---

## 5. Salesforce API Reference

- **Object:** `Contract`
- **Upsert Endpoint:** `PATCH /services/data/v59.0/sobjects/Contract/<ExternalId__c>/<value>`
- **Key Fields:** `AccountId`, `StartDate`, `EndDate`, `ContractTerm`, `Status`, `ExternalId__c`
- **External ID Field:** `ExternalId__c` (maps to source system record ID — must be configured in Salesforce)

---

## 6. Memory Schema (this skill)

```json
{
  "skill": "Contract Logging Agent",
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
| `400` | Bad request / missing required field | Log and raise Jira ticket |
| `409` | Duplicate record conflict | Switch to PATCH (update) mode, retry once |
| `500` | Salesforce server error | Wait 30s, retry once; raise Jira ticket if still failing |

---

## 8. Execution Checklist

```
[ ] Read Memory/memory.json — identify last_processed_id
[ ] Fetch new records from upstream (records after last_processed_id)
[ ] For each record:
    [ ] Check if ExternalId__c already exists in Salesforce (GET query)
    [ ] If exists → PATCH (update)
    [ ] If not exists → POST (create)
    [ ] On success → update memory.json state
    [ ] On failure → write to error.log → check known_issues → retry or raise Jira ticket
[ ] Write final state back to memory.json
```
