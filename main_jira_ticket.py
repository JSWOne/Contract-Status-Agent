import json
import sys
from pathlib import Path

from flask import Flask, jsonify, request


TOOLS_DIR = Path(__file__).parent / "ContractSOAgent" / "Jira Ticket Agent" / "Tools"
sys.path.insert(0, str(TOOLS_DIR))

from close_ticket import close_ticket  # noqa: E402
from create_ticket import create_or_update_ticket  # noqa: E402
from update_ticket import update_ticket  # noqa: E402


app = Flask(__name__)


@app.get("/")
def health():
    return jsonify({"service": "jira-ticket-agent", "status": "ok"})


@app.post("/tickets")
def create_ticket_route():
    payload = request.get_json(silent=True) or {}
    try:
        result = create_or_update_ticket(payload)
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/tickets/<ticket_id>/comment")
@app.put("/tickets/<ticket_id>/comment")
def update_ticket_route(ticket_id: str):
    payload = request.get_json(silent=True) or {}
    comment = payload.get("comment") or payload.get("message")
    status = payload.get("status")
    if not comment:
        return jsonify({"ok": False, "error": "comment is required"}), 400

    try:
        result = update_ticket(ticket_id, comment, status)
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/tickets/<ticket_id>/close")
def close_ticket_route(ticket_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = close_ticket(ticket_id, payload.get("comment"))
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def cloud_function_entry(request):
    payload = request.get_json(silent=True) if request else {}
    result = create_or_update_ticket(payload or {})
    return json.dumps(result), 200, {"Content-Type": "application/json"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
