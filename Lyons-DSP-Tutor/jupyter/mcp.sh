#!/usr/bin/env bash
# Jupyter MCP server (stdio) for Claude Code. Connects to the JupyterLab started by start-lab.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -s .jupyter-token ]]; then
  echo "No .jupyter-token: start JupyterLab first with jupyter/start-lab.sh" >&2
  exit 1
fi
export JUPYTER_URL=http://127.0.0.1:8888
export JUPYTER_TOKEN="$(cat .jupyter-token)"
export ALLOW_IMG_OUTPUT=true
exec .venv/bin/jupyter-mcp-server start --transport stdio
