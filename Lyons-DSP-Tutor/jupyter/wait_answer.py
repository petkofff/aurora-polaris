"""Wait until the learner submits an answer in a live JupyterLab notebook.

The tutor runs this in the background after asking a question in the notebook. It exits
(waking the tutor) when the learner submits, and prints the cells they wrote.

A submission is either:
  - a non-empty cell the learner wrote or changed, followed by a new cell
    (Shift+Enter on the last cell adds one), or
  - a code cell the learner ran.

Usage (from the tutor's folder, with JupyterLab started by jupyter/start-lab.sh):
  .venv/bin/python jupyter/wait_answer.py learner/lab/ch03.ipynb [--timeout 1200]

Exit codes: 0 answer submitted · 2 timed out · 1 error (e.g. JupyterLab not running).

Environment: JUPYTER_URL (default http://127.0.0.1:8888) and JUPYTER_TOKEN (default: read from
.jupyter-token) override the server, e.g. for the tests.
"""

import argparse
import asyncio
import logging
import os
import sys
import time

POLL = 0.5          # seconds between checks of the shared document
MAX_OUTPUT = 2000   # characters of text output printed per cell
SERVER = os.environ.get("JUPYTER_URL", "http://127.0.0.1:8888")


def connected(client):
    """The client drops its connection task when the websocket closes (e.g. JupyterLab stopped)."""
    return getattr(client, "_NbModelClient__run", None) is not None


def cell_state(cell):
    source = cell.get("source", "")
    if isinstance(source, list):
        source = "".join(source)
    return source, cell.get("execution_count")


def snapshot(client):
    cells = []
    for i in range(len(client)):
        cell = client[i]
        source, count = cell_state(cell)
        cells.append({"id": cell.get("id"), "type": cell.get("cell_type"), "source": source,
                      "count": count, "outputs": cell.get("outputs", [])})
    return cells


def find_submission(baseline, cells):
    """Return the indices of the learner's submitted cells, or None."""
    changed = []
    for i, cell in enumerate(cells):
        old = baseline.get(cell["id"])
        if old is None:
            if cell["source"].strip() or cell["count"] is not None:
                changed.append(i)
        elif (cell["source"], cell["count"]) != old:
            changed.append(i)
    if not changed:
        return None
    for i in changed:
        cell = cells[i]
        old = baseline.get(cell["id"])
        ran = cell["type"] == "code" and cell["count"] is not None and (old is None or cell["count"] != old[1])
        followed_by_new = any(c["id"] not in baseline for c in cells[i + 1:])
        if ran or (cell["source"].strip() and followed_by_new):
            return changed
    return None


def text_outputs(outputs):
    parts = []
    for out in outputs:
        kind = out.get("output_type")
        if kind == "stream":
            text = out.get("text", "")
            parts.append("".join(text) if isinstance(text, list) else text)
        elif kind in ("execute_result", "display_data"):
            data = out.get("data", {})
            if "text/plain" in data:
                text = data["text/plain"]
                parts.append("".join(text) if isinstance(text, list) else text)
            if any(k.startswith("image/") for k in data):
                parts.append("[image output: read this cell with read_cell to see it]")
        elif kind == "error":
            parts.append(f"{out.get('ename')}: {out.get('evalue')}")
    text = "\n".join(p.rstrip("\n") for p in parts)
    return text[:MAX_OUTPUT] + (" …[truncated]" if len(text) > MAX_OUTPUT else "")


def report(baseline, cells, indices):
    print("ANSWER SUBMITTED")
    for i in indices:
        cell = cells[i]
        if not cell["source"].strip() and cell["count"] is None:
            continue
        old = baseline.get(cell["id"])
        ran = cell["type"] == "code" and cell["count"] is not None and (old is None or cell["count"] != old[1])
        state = ", ran" if ran else (", edited, not re-run" if cell["type"] == "code" else "")
        print(f"\n--- cell {i} ({cell['type']}{state})")
        print(cell["source"])
        if cell["type"] == "code" and cell["outputs"]:
            print("--- output" + ("" if ran else " (from an earlier run, may be stale)"))
            print(text_outputs(cell["outputs"]))
    print(f"\nThe notebook now has {len(cells)} cells. Append new cells at the end (index -1).")


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notebook", help="notebook path relative to the tutor's folder")
    parser.add_argument("--timeout", type=float, default=1200, help="seconds to wait (default 1200)")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)  # the client library logs tracebacks; we print our own errors

    from jupyter_nbmodel_client import NbModelClient, get_jupyter_notebook_websocket_url

    token = os.environ.get("JUPYTER_TOKEN")
    if not token:
        try:
            with open(".jupyter-token") as f:
                token = f.read().strip()
        except OSError:
            print("No .jupyter-token: start JupyterLab with jupyter/start-lab.sh", file=sys.stderr)
            return 1

    try:
        ws_url = get_jupyter_notebook_websocket_url(SERVER, args.notebook, token)
    except Exception as e:  # server down, notebook missing, bad token
        print(f"Can't open {args.notebook} in JupyterLab at {SERVER}: {e}", file=sys.stderr)
        return 1

    try:
        async with NbModelClient(ws_url, path=args.notebook, username="tutor-watcher") as client:
            sync_deadline = time.monotonic() + 30
            while not client.synced:
                if not connected(client) or time.monotonic() > sync_deadline:
                    raise ConnectionError("the notebook didn't open (does the file exist?)")
                await asyncio.sleep(0.1)
            baseline = {c["id"]: (c["source"], c["count"]) for c in snapshot(client)}
            print(f"Waiting for an answer in {args.notebook} …", file=sys.stderr, flush=True)
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL)
                if not connected(client):
                    raise ConnectionError("connection to JupyterLab closed")
                cells = snapshot(client)
                submitted = find_submission(baseline, cells)
                if submitted is not None:
                    report(baseline, cells, submitted)
                    return 0
            print(f"TIMED OUT after {args.timeout:.0f} s with no answer submitted.")
            return 2
    except Exception as e:  # connection refused or closed, notebook missing
        print(f"Lost or couldn't open {args.notebook} in JupyterLab at {SERVER}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sys.exit(asyncio.run(main()))
