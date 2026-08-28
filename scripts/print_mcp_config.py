#!/usr/bin/env python3
"""Print a ready-to-paste MCP client configuration for this checkout.

Fills in the absolute paths so you do not have to. Writes to stdout; nothing is
modified unless you pass --write, which creates .mcp.json in the project root
(gitignored) for Claude Code to pick up.

    python scripts/print_mcp_config.py
    python scripts/print_mcp_config.py --write

The Neo4j password is deliberately not included. The server reads .env from the
project directory it is launched in, which is where it already lives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def config() -> dict:
    python = REPO_ROOT / ".venv" / "bin" / "python"
    if not python.exists():  # Windows layout
        python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return {
        "mcpServers": {
            "scipy-india-organizing": {
                "command": str(python),
                "args": ["-m", "scipy_india_kg.mcp"],
                "cwd": str(REPO_ROOT),
                "env": {
                    "PYTHONPATH": str(REPO_ROOT / "src"),
                    "TOKENIZERS_PARALLELISM": "false",
                },
            }
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write .mcp.json in the project root")
    args = parser.parse_args()

    payload = config()
    rendered = json.dumps(payload, indent=2)

    if args.write:
        target = REPO_ROOT / ".mcp.json"
        if target.exists():
            print(f"{target} already exists; not overwriting.", file=sys.stderr)
            return 1
        target.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {target}. Restart Claude Code in this directory to pick it up.")
        return 0

    print(rendered)
    print(
        "\n# Claude Code: save this as .mcp.json in the project root "
        "(or run with --write).\n"
        "# Claude Desktop: merge the mcpServers block into "
        "claude_desktop_config.json.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
