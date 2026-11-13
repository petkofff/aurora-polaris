"""Shared helpers for the tests of jupyter/wait_answer.py.

The integration tests start their own JupyterLab in a temporary folder, on a free port, with a
random token and isolated Jupyter config/data/runtime folders. They never touch the learner's
JupyterLab, `learner/`, or `.jupyter-token`.
"""

import asyncio
import json
import os
import secrets
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TUTOR = Path(__file__).resolve().parent.parent
WATCHER = TUTOR / "jupyter" / "wait_answer.py"
sys.path.insert(0, str(TUTOR / "jupyter"))


def have_jupyter():
    """True when the venv packages the integration tests need are importable."""
    try:
        import jupyter_nbmodel_client  # noqa: F401
        import jupyterlab  # noqa: F401
        import jupyter_server_ydoc  # noqa: F401
    except ImportError:
        return False
    return shutil.which("jupyter-lab", path=str(Path(sys.executable).parent)) is not None


# --- cells for the unit tests ------------------------------------------------------------

def cell(id, source="", type="markdown", count=None, outputs=None):
    """A cell as wait_answer.snapshot() returns it."""
    return {"id": id, "type": type, "source": source, "count": count, "outputs": outputs or []}


def baseline_of(cells):
    return {c["id"]: (c["source"], c["count"]) for c in cells}


# --- a throwaway JupyterLab ------------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    """A JupyterLab server in a temporary folder. Use as a context manager, or start()/stop()."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="wait-answer-test-"))
        self.port = free_port()
        self.token = secrets.token_hex(16)
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self, timeout=60):
        env = dict(os.environ)
        for var in ("JUPYTER_CONFIG_DIR", "JUPYTER_DATA_DIR", "JUPYTER_RUNTIME_DIR"):
            env[var] = str(self.root / ".jupyter-env" / var.lower())
        lab = Path(sys.executable).parent / "jupyter-lab"
        self.proc = subprocess.Popen(
            [str(lab), "--no-browser", "--ip", "127.0.0.1", "--port", str(self.port),
             "--ServerApp.port_retries=0", f"--IdentityProvider.token={self.token}",
             f"--ServerApp.root_dir={self.root}"],
            cwd=self.root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("JupyterLab exited during startup")
            try:
                with urllib.request.urlopen(f"{self.url}/api/status?token={self.token}", timeout=2):
                    return self
            except OSError:
                time.sleep(0.3)
        self.stop()
        raise RuntimeError("JupyterLab didn't start in time")

    def kill(self):
        """Simulate a crash."""
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.kill()
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def write_notebook(self, path, cells):
        """Create a notebook on disk. cells: list of (id, cell_type, source)."""
        nb = {"nbformat": 4, "nbformat_minor": 5,
              "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3",
                                          "language": "python"}},
              "cells": [{"id": i, "cell_type": t, "metadata": {}, "source": s,
                         **({"outputs": [], "execution_count": None} if t == "code" else {})}
                        for i, t, s in cells]}
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(nb, indent=1))
        return path


# --- the learner, editing the live notebook ------------------------------------------------------

def learner(lab, path, action):
    """Edit the live notebook as the learner would. action(client) changes the model."""
    async def run():
        import logging
        logging.disable(logging.CRITICAL)
        from jupyter_nbmodel_client import NbModelClient, get_jupyter_notebook_websocket_url
        url = get_jupyter_notebook_websocket_url(lab.url, path, lab.token)
        async with NbModelClient(url, path=path, username="test-learner") as client:
            await asyncio.wait_for(client.wait_until_synced(), 30)
            action(client)
            await asyncio.sleep(1.0)  # let the change reach the server before disconnecting
    asyncio.run(run())


def type_into_last(text):
    def action(client):
        client.set_cell_source(len(client) - 1, text)
    return action


def shift_enter(client):
    """Shift+Enter on the last cell: JupyterLab adds an empty cell below."""
    client.add_code_cell("")


def run_code(source, output, count=1):
    """Add a code cell and record a run of it (outputs and execution count, as the kernel would)."""
    def action(client):
        i = client.add_code_cell(source)
        c = dict(client[i])
        c["execution_count"] = count
        c["outputs"] = [{"output_type": "stream", "name": "stdout", "text": output}]
        client[i] = c
    return action


# --- the watcher as a subprocess --------------------------------------------------------------

class Watcher:
    """jupyter/wait_answer.py running against a test JupyterLab."""

    def __init__(self, lab_url, token, notebook, timeout=30):
        env = dict(os.environ, JUPYTER_URL=lab_url, JUPYTER_TOKEN=token)
        self.proc = subprocess.Popen(
            [sys.executable, str(WATCHER), notebook, "--timeout", str(timeout)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.stderr = ""

    def wait_until_waiting(self, timeout=30):
        """Block until the watcher has its baseline (it prints 'Waiting…' to stderr)."""
        sel = selectors.DefaultSelector()
        sel.register(self.proc.stderr, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if sel.select(timeout=0.2):
                line = self.proc.stderr.readline()
                if not line:
                    break  # watcher exited
                self.stderr += line
                if line.startswith("Waiting for an answer"):
                    return True
        return False

    def running_after(self, seconds):
        time.sleep(seconds)
        return self.proc.poll() is None

    def finish(self, timeout=30):
        """Wait for the exit; return (exit code, stdout, stderr)."""
        out, err = self.proc.communicate(timeout=timeout)
        return self.proc.returncode, out, self.stderr + err

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate()
