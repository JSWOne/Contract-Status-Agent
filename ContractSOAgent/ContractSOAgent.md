# ContractSOAgent — Master Orchestrator
> **JSW One Platforms | Salesforce Automation System**
> Version: 1.0.0 | Owner: Milind Kumar | Last Updated: 2026-04-29

---

## 1. Mission Statement

The **ContractSOAgent** is the root-level orchestrator for the end-to-end automation of Contract and Sales Order (SO) operations for **JSW One Platforms** within the **JSW Steel Salesforce portal** (`jswoneplatforms.my.salesforce.com`).

This agent coordinates a network of specialised sub-agents (Skills) to:
- Automatically log new Contracts and Sales Orders into Salesforce from upstream sources.
- Track and report real-time statuses of Contracts and SOs.
- Create and manage Jira tickets for exceptions, failures, and manual review items.
- Self-heal from errors using structured Logs and persistent Memory.

---

## 2. Project Folder Structure

```
ContractSOAgent/
│
├── ContractSOAgent.md              ← YOU ARE HERE (Master Orchestrator)
│
├── Contract Logging Agent/
│   ├── ContractLoggingAgent.md     ← Skill instructions & objectives
│   ├── Tools/                      ← Python/JS scripts for execution
│   ├── Memory/                     ← Persistent state & action history
│   └── Logs/                       ← Error logs & auto-fix records
│
├── Contract Status Agent/
│   ├── ContractStatusAgent.md
│   ├── Tools/
│   ├── Memory/
│   └── Logs/
│
├── SO Logging Agent/
│   ├── SOLoggingAgent.md
│   ├── Tools/
│   ├── Memory/
│   └── Logs/
│
├── SO Status Agent/
│   ├── SOStatusAgent.md
│   ├── Tools/
│   ├── Memory/
│   └── Logs/
│
└── Jira Ticket Agent/
    ├── JiraTicketAgent.md
    ├── Tools/
    ├── Memory/
    └── Logs/
```

---

## 3. Sub-Agent Registry (Skills)

| # | Skill Name | Skill File | Primary Responsibility |
|---|------------|------------|------------------------|
| 1 | **Contract Logging Agent** | `ContractLoggingAgent.md` | Fetch contract data from source and create/update Contract records in Salesforce |
| 2 | **Contract Status Agent** | `ContractStatusAgent.md` | Poll and report the live status of Contracts in Salesforce |
| 3 | **SO Logging Agent** | `SOLoggingAgent.md` | Fetch Sales Order data and create/update SO records in Salesforce |
| 4 | **SO Status Agent** | `SOStatusAgent.md` | Poll and report the live status of Sales Orders in Salesforce |
| 5 | **Jira Ticket Agent** | `JiraTicketAgent.md` | Create, update, and close Jira tickets for failures, exceptions, and review items |

---

## 4. Agent Architecture & Orchestration Flow

```
                        ┌─────────────────────────┐
                        │    ContractSOAgent       │
                        │   (Master Orchestrator)  │
                        └──────────────┬───────────┘
                                       │
               ┌───────────────────────┼───────────────────────┐
               │                       │                        │
     ┌─────────┴─────────┐   ┌─────────┴─────────┐  ┌─────────┴──────────┐
     │  Contract Logging  │   │  SO Logging    │  │  Jira Ticket       │
     │       Agent        │   │     Agent      │  │      Agent         │
     └─────────┬──────────┘   └─────────┬──────────┘  └──────────▲──────────┘
               │                        │                          │
     ┌─────────┴──────────┐  ┌──────────┴─────────┐               │
     │  Contract Status   │  │   SO Status    │   (on error / exception)
     │       Agent        │  │     Agent      │                    │
     └─────────┬──────────┘  └─────────┬──────────┘               │
               └────────────────────── ┴──────────────────────────-┘
                                 Salesforce CRM
                         (jswoneplatforms.my.salesforce.com)
```

### Orchestration Decision Logic

```
START
  │
  ├──► Is the trigger a NEW Contract or SO record?
  │       └──► YES → Invoke [Contract/SO Logging Agent]
  │               ├──► On Success → Invoke [Contract/SO Status Agent] to confirm
  │               └──► On Failure → Invoke [Jira Ticket Agent] to raise ticket
  │
  ├──► Is the trigger a STATUS CHECK request?
  │       └──► YES → Invoke [Contract/SO Status Agent]
  │               └──► On Stale/Unexpected Status → Invoke [Jira Ticket Agent]
  │
  └──► Is any sub-agent throwing a REPEATED ERROR?
          └──► YES → Check that skill's Logs/ → Apply auto-fix → Retry once
                  └──► Still failing → Invoke [Jira Ticket Agent] + Halt
```

---

## 5. Shared Standards Across All Skills

### 5.1 Tools/ Folder
- All executable scripts (Python `.py` or JavaScript `.js`) live here.
- Each tool file must have a header block:
  ```python
  # Tool Name   : <descriptive name>
  # Skill       : <parent skill name>
  # Version     : <x.y.z>
  # Last Updated: <YYYY-MM-DD>
  # Description : <what this tool does in 1-2 lines>
  # Dependencies: <list pip/npm packages required>
  ```
- Tools must be **idempotent** where possible — safe to re-run without duplicating data.
- All Salesforce API calls use the REST API endpoint pattern:
  `https://jswoneplatforms.my.salesforce.com/services/data/v59.0/`
- Authentication: OAuth2 Bearer Token (token refresh logic must be included in every tool that calls Salesforce).

### 5.2 Memory/ Folder
- Each skill maintains a `memory.json` file that is **auto-updated** after every tool execution.
- Memory schema:

  ```json
  {
    "skill": "<skill name>",
    "last_run": "<ISO timestamp>",
    "last_action": "<description of last tool invoked>",
    "state": {
      "last_processed_id": "<Salesforce record ID or source ID>",
      "pending_items": [],
      "completed_items": []
    },
    "known_issues": [
      {
        "error_code": "<error identifier>",
        "description": "<what the error is>",
        "resolution": "<how it was resolved>",
        "resolved_at": "<ISO timestamp>"
      }
    ]
  }
  ```

- Before every tool run, the agent **reads memory** to determine resume point and skip already-processed records.
- After every successful tool run, memory is **written back** with the updated state.

### 5.3 Logs/ Folder
- Each skill maintains an `error.log` file in append-only mode.
- Log entry format (one JSON object per line — NDJSON):

  ```json
  {
    "timestamp": "<ISO timestamp>",
    "skill": "<skill name>",
    "tool": "<script filename>",
    "error_code": "<HTTP status or exception type>",
    "error_message": "<full error string>",
    "input_payload": { },
    "resolution_attempted": "<auto-fix description or null>",
    "resolution_status": "success | failed | pending",
    "ticket_id": "<Jira ticket ID if raised, else null>"
  }
  ```

- **Auto-fix Protocol**: Before executing any tool, the orchestrator checks `error.log` for the last 5 entries. If a matching error pattern is found with a recorded resolution, it applies that resolution automatically before retrying.
- If auto-fix fails after 1 retry, the **Jira Ticket Agent** is invoked and execution halts for that record (others continue).

---

## 6. Salesforce Integration Reference

| Parameter | Value |
|-----------|-------|
| Org URL | `https://jswoneplatforms.my.salesforce.com` |
| API Version | `v59.0` |
| Auth Method | OAuth2 (Username-Password or Connected App JWT) |
| Key Objects | `Contract`, `Order` (SO), `Account`, `Opportunity` |
| REST Base | `/services/data/v59.0/sobjects/` |
| SOQL Query Endpoint | `/services/data/v59.0/query/?q=SELECT...` |

---

## 7. Jira Integration Reference

| Parameter | Value |
|-----------|-------|
| Project | *(To be defined in JiraTicketAgent.md)* |
| Ticket Types | `Bug` (tool failures), `Task` (manual review), `Story` (feature gaps) |
| Priority Logic | P1 = data loss risk, P2 = logging failure, P3 = status mismatch, P4 = warning |
| Auto-close | Ticket auto-closed when resolution is logged in Memory and confirmed in next run |

---

## 8. Invocation & Trigger Sources

| Trigger Type | Source | Target Skill |
|--------------|--------|-------------|
| New Contract record available | Upstream API / Excel / n8n Webhook | Contract Logging Agent |
| New SO record available | Upstream API / Excel / n8n Webhook | SO Logging Agent |
| Scheduled status poll | n8n Cron (frequency TBD) | Contract Status Agent, SO Status Agent |
| Manual status check | Operator request / n8n trigger | Contract Status Agent or SO Status Agent |
| Tool failure detected | Internal error handler | Jira Ticket Agent |
| Repeated error (≥2 occurrences) | Auto-fix check in Logs/ | Jira Ticket Agent + Halt |

---

## 9. Development Conventions

### Naming Conventions
- Tool files: `snake_case.py` or `camelCase.js` (e.g., `log_contract.py`, `checkSOStatus.js`)
- Memory files: always named `memory.json` within each skill's `Memory/` folder
- Log files: always named `error.log` within each skill's `Logs/` folder
- Skill instruction files: `PascalCase` matching the skill name (e.g., `ContractLoggingAgent.md`)

### Error Handling Rules
1. Every API call must have a **try/except** (Python) or **try/catch** (JS) block.
2. All caught errors must be written to `Logs/error.log` before re-raising or continuing.
3. After writing to log, check `Memory/memory.json` `known_issues` array for a matching `error_code`.
4. If match found → apply resolution → retry **once**.
5. If no match or retry fails → trigger Jira Ticket Agent → log `ticket_id` back into the error log entry.

### Data Safety Rules
- Never overwrite an existing Salesforce record without first reading its current state and logging the `before` snapshot in Memory.
- All `PATCH` / `DELETE` operations require a confirmation flag in the tool's config.
- Dry-run mode must be available in every tool via a `DRY_RUN = True` flag at the top of the file.

---

## 10. Rollout Phases

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 0 | Folder structure + ContractSOAgent.md scaffolding | ✅ Done |
| Phase 1 | Contract Logging Agent — Tools + Memory + Logs | 🔲 Pending |
| Phase 2 | Contract Status Agent — Tools + Memory + Logs | 🔲 Pending |
| Phase 3 | SO Logging Agent — Tools + Memory + Logs | 🔲 Pending |
| Phase 4 | SO Status Agent — Tools + Memory + Logs | 🔲 Pending |
| Phase 5 | Jira Ticket Agent — Tools + Memory + Logs | 🔲 Pending |
| Phase 6 | End-to-end integration test + n8n wiring | 🔲 Pending |

---

## 11. How to Start a New Skill Build

When beginning development on any sub-agent skill, follow this checklist:

```
[ ] 1. Open the skill's .md file (e.g., ContractLoggingAgent.md)
[ ] 2. Read the Objective, Inputs, Outputs, and API references defined there
[ ] 3. Check Logs/error.log — is there a prior failure to learn from?
[ ] 4. Check Memory/memory.json — what was the last successful state?
[ ] 5. Write the tool script in Tools/ with proper header block
[ ] 6. Set DRY_RUN = True and test end-to-end
[ ] 7. Set DRY_RUN = False and run with 1 record
[ ] 8. Confirm Memory is updated and no errors in Logs
[ ] 9. Update this file's Phase table above
```

---

## 12. Owner & Contact

| Field | Detail |
|-------|--------|
| Project Owner | Milind Kumar |
| Organisation | JSW One Platforms |
| Salesforce Org | `jswoneplatforms.my.salesforce.com` |
| Orchestrator Version | 1.0.0 |
| Architecture Style | Agentic Multi-Skill (Hierarchical Orchestrator Pattern) |

---

*This file is the single source of truth for the ContractSOAgent system. All sub-agent Skill files must align with the standards defined here. Update this file whenever a new skill is added, a convention changes, or a new integration is introduced.*
