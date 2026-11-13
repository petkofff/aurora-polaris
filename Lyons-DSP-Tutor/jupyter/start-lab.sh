#!/usr/bin/env bash
# Start JupyterLab for the tutor, on localhost only, with a token kept in .jupyter-token.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -s .jupyter-token ]]; then
  ( umask 077; .venv/bin/python -c 'import secrets; print(secrets.token_hex(24))' > .jupyter-token )
fi
mkdir -p learner/lab
exec .venv/bin/jupyter lab --ip 127.0.0.1 --port 8888 --ServerApp.port_retries=0 \
  --IdentityProvider.token "$(cat .jupyter-token)" "$@"
