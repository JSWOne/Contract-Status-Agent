import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).parent / "ContractSOAgent" / "Contract Logging Agent" / "Tools"
sys.path.insert(0, str(TOOLS_DIR))

from webhook_listener import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
