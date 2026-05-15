"""
Tool Name   : jira_client.py
Skill       : Jira Ticket Agent
Version     : 1.0.0
Last Updated: 2026-05-15
Description : Shared Jira Cloud client, memory, and log helpers for Jira Ticket Agent tools.
Dependencies: requests, python-dotenv
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
MEMORY_PATH = BASE_DIR / "Memory" / "memory.json"
ERROR_LOG_PATH = BASE_DIR / "Logs" / "error.log"

load_dotenv(Path(__file__).with_name(".env"))
load_dotenv(BASE_DIR / ".env")


class JiraAgentError(Exception):
    """Base exception for Jira Ticket Agent failures."""


class JiraConfigError(JiraAgentError):
    """Raised when required Jira configuration is missing."""


class JiraApiError(JiraAgentError):
    """Raised when Jira returns an unsuccessful API response."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {
            "skill": "Jira Ticket Agent",
            "last_run": None,
            "last_action": None,
            "state": {
                "last_processed_id": None,
                "pending_items": [],
                "completed_items": [],
            },
            "known_issues": [],
        }

    return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))


def save_memory(memory: dict[str, Any], action: str) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    memory["last_run"] = utc_now()
    memory["last_action"] = action
    MEMORY_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")


def write_error_log(
    *,
    tool: str,
    error_code: str,
    error_message: str,
    input_payload: dict[str, Any] | None = None,
    ticket_id: str | None = None,
) -> None:
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": utc_now(),
        "skill": "Jira Ticket Agent",
        "tool": tool,
        "error_code": error_code,
        "error_message": error_message,
        "input_payload": input_payload or {},
        "resolution_attempted": None,
        "resolution_status": "pending",
        "ticket_id": ticket_id,
    }
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def make_fingerprint(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("affected_skill", "")).strip().lower(),
        str(payload.get("affected_record_id", "")).strip().lower(),
        str(payload.get("summary", "")).strip().lower(),
        str(payload.get("error_code", "")).strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def priority_name(priority: str) -> str:
    mapping = {
        "P1": "Highest",
        "P2": "High",
        "P3": "Medium",
        "P4": "Low",
    }
    return mapping.get(priority.upper(), priority)


class JiraClient:
    def __init__(self) -> None:
        domain = os.getenv("JIRA_DOMAIN", "").strip()
        email = os.getenv("JIRA_EMAIL", "").strip()
        token = os.getenv("JIRA_API_TOKEN", "").strip()

        if not domain or not email or not token:
            raise JiraConfigError(
                "Set JIRA_DOMAIN, JIRA_EMAIL, and JIRA_API_TOKEN before using Jira tools."
            )

        if domain.startswith("http://") or domain.startswith("https://"):
            self.base_url = domain.rstrip("/")
        else:
            self.base_url = f"https://{domain.rstrip('/')}"

        self.session = requests.Session()
        self.session.auth = requests.auth.HTTPBasicAuth(email, token)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise JiraApiError(f"Could not connect to Jira: {exc}") from exc

        if response.status_code == 204:
            return None

        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}

        if not response.ok:
            message = json.dumps(data)[:1000]
            raise JiraApiError(f"Jira returned HTTP {response.status_code}: {message}")

        return data

    def create_issue(
        self,
        *,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        priority: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": adf_doc(description),
            "priority": {"name": priority_name(priority)},
        }
        if labels:
            fields["labels"] = labels

        return self.request("POST", "/rest/api/3/issue", json={"fields": fields})

    def add_comment(self, issue_key: str, comment: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            json={"body": adf_doc(comment)},
        )

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        data = self.request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        return data.get("transitions", [])

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        self.request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": transition_id}},
        )


def adf_doc(text: str) -> dict[str, Any]:
    lines = str(text or "").splitlines() or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}] if line else [],
            }
            for line in lines
        ],
    }
