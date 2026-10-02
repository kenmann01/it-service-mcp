"""Call one Internal IT tool over stdio and print the JSON result."""

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from mcp_client import call_tool


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: call_tool.py <tool-name> '<json-arguments>'")
    name = sys.argv[1]
    arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    json.dump(call_tool(name, arguments), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
