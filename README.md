# Contract SO AI Agent

Automation workspace for JSW One Contract and Sales Order agents.

Current implemented module:

- `ContractSOAgent/Contract Status Agent`
  - Scrapes recent Salesforce contract statuses with Playwright.
  - Updates the OneDrive Excel tracker through Power Automate.
  - Sends Teams status-change cards through Power Automate.
  - Runs as a one-shot orchestrator suitable for Cloud Scheduler / Cloud Run.

Secrets and runtime state are intentionally excluded from git. Configure required values with environment variables or a local `.env` file based on each tool's `.env.example`.
