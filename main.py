import json
import sys
from pathlib import Path

from flask import Flask, jsonify, request


TOOLS_DIR = Path(__file__).parent / "ContractSOAgent" / "Contract Status Agent" / "Tools"
sys.path.insert(0, str(TOOLS_DIR))

import run_contract_status_agent  # noqa: E402


app = Flask(__name__)


@app.get("/")
def health():
    return jsonify({"service": "contract-status-agent", "status": "ok"})


@app.post("/run")
@app.get("/run")
def run_agent():
    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id") or request.args.get("run_id")
    try:
        result = run_contract_status_agent.run_once(run_id=run_id)
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"run_status": "failed", "error": str(exc)}), 500


def cloud_function_entry(request):
    payload = request.get_json(silent=True) if request else {}
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    result = run_contract_status_agent.run_once(run_id=run_id)
    return json.dumps(result), 200, {"Content-Type": "application/json"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
