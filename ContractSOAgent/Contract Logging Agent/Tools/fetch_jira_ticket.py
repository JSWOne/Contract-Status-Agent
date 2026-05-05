"""
Tool: fetch_jira_ticket.py
Purpose: Fetch one Jira Cloud O360 ticket and return normalized fields for Contract Logging.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))


class JiraAuthError(Exception):
    pass


class JiraConnectionError(Exception):
    pass


def fetch_jira_ticket(ticket_id: str) -> dict | None:
    domain = os.environ["JIRA_DOMAIN"].strip()
    email = os.environ["JIRA_EMAIL"].strip()
    api_token = os.environ["JIRA_API_TOKEN"].strip()

    url = f"https://{domain}/rest/api/3/issue/{ticket_id}?expand=names"
    try:
        response = requests.get(
            url,
            auth=requests.auth.HTTPBasicAuth(email, api_token),
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.exceptions.RequestException as exc:
        raise JiraConnectionError(f"Could not connect to Jira: {exc}") from exc

    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise JiraAuthError(f"Jira authentication failed with HTTP {response.status_code}")
    if not response.ok:
        raise JiraConnectionError(
            f"Jira returned HTTP {response.status_code}: {response.text[:300]}"
        )

    return _parse_ticket(response.json(), domain)


def _parse_ticket(raw: dict, domain: str) -> dict:
    fields = raw.get("fields", {})
    names = raw.get("names", {})
    key = raw.get("key", "")
    custom_fields = {}

    for field_id, value in fields.items():
        if not field_id.startswith("customfield_") or value is None:
            continue
        field_name = names.get(field_id, field_id)
        str_value = _extract_field_value(value)
        if str_value:
            custom_fields[field_name] = str_value

    return {
        "key": key,
        "summary": fields.get("summary", ""),
        "status": _extract_field_value(fields.get("status")),
        "reporter": _extract_field_value(fields.get("reporter")),
        "created": (fields.get("created") or "")[:10],
        "updated": (fields.get("updated") or "")[:10],
        "url": f"https://{domain}/browse/{key}",
        "custom_fields": custom_fields,
    }


def _extract_field_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "key"):
            if value.get(key) is not None:
                result = str(value[key]).strip()
                child = value.get("child")
                if isinstance(child, dict) and child.get("value"):
                    result = f"{result} - {child['value']}"
                return result
        return ""
    if isinstance(value, list):
        return ", ".join(part for part in (_extract_field_value(v) for v in value) if part)
    return str(value).strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_jira_ticket.py O360-12345")
        sys.exit(1)
    ticket = fetch_jira_ticket(sys.argv[1].upper())
    print(json.dumps(ticket, indent=2))
