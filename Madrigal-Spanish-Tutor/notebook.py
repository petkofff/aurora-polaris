#!/usr/bin/env python3
"""The tutor's notebook: a local web page beside the terminal, where the learner answers batches of
prompts (each in its own numbered field), rewrites what they got wrong, and finds the tutor's notes.

The whole session stays on the page and is saved to learner/notebook/YYYY-MM-DD.md for rereading.

Commands:
  start [--title T]           start the server (or reuse it) and print the link; begins a new session
                              unless today's session is still running
  status                      link, session and score (exit 1 if the server isn't running)
  title TEXT                  set the heading (lesson and topic); a change starts a new section
  note [--title T] TEXT       post a note (Markdown: **bold**, *italic*, lists, tables); TEXT - reads stdin
  ask [--title T] [--wait [--timeout S]] PROMPT...
                              post a batch; with --wait, also wait for the answers (default 1200 s)
  watch [--timeout S]         print the answers and rewrites as the learner sends them, each once,
                              until the server stops (default 1800 s; 0 = no limit). Prints nothing
                              else on stdout except a NOTEBOOK DOWN line if the server goes away.
                              Meant for a background watcher whose output wakes the tutor.
  wait [--timeout S]          wait for the answers or rewrites of the latest batch (0 = check once)
  feedback [--comment C] [--wait [--timeout S]] MARK...
                              mark the answers that `watch` / `wait` printed, in order:
                              ok · 'ok: NOTE' · CORRECT · 'CORRECT | REASON' (the last two are wrong).
                              A wrong answer opens a rewrite field; after 3 tries the item closes.
                              With --wait, then wait for the rewrites like `wait`.
  cancel                      withdraw the latest batch (e.g. answered in the terminal)
  end                         put the session score on the page and print it
  stop                        stop the server
  serve [--port P] [--title T]
                              run the server in the foreground (`start` runs this)

Exit codes: 0 ok (watch: the server was stopped) · 1 error (e.g. server not running) · 2 timed out
            · 3 batch withdrawn or replaced · 4 (wait --timeout 0) not answered yet.

The server listens on 127.0.0.1 only. Every request needs the token from .notebook-token (created on
first start, next to this script); the page gets it from its link.

Env: NOTEBOOK_PORT (default 8765), NOTEBOOK_TOKEN_FILE (default .notebook-token next to this script),
     NOTEBOOK_DIR (default learner/notebook next to this script),
     NOTEBOOK_TODAY (YYYY-MM-DD, override today's date — for testing).
"""
import argparse
import copy
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

HERE = Path(__file__).resolve().parent
TOKEN_FILE = Path(os.environ.get("NOTEBOOK_TOKEN_FILE", HERE / ".notebook-token"))
NOTEBOOK_DIR = Path(os.environ.get("NOTEBOOK_DIR", HERE / "learner" / "notebook"))
SLICE = 25            # seconds per long-poll request
MAX_PROMPTS = 30
MAX_TRIES = 3         # the answer and two rewrites
MAX_TEXT = 500        # characters per prompt, answer, mark or title
MAX_NOTE = 20000
MAX_BODY = 256 * 1024

try:
    PORT = int(os.environ.get("NOTEBOOK_PORT", "8765"))
except ValueError:
    sys.exit(f"error: NOTEBOOK_PORT must be a number, got '{os.environ['NOTEBOOK_PORT']}'")


def today() -> str:
    override = os.environ.get("NOTEBOOK_TODAY")
    if not override:
        return date.today().isoformat()
    try:
        return date.fromisoformat(override).isoformat()
    except ValueError:
        sys.exit(f"error: NOTEBOOK_TODAY must be YYYY-MM-DD, got '{override}'")


def read_token(create=False) -> str:
    try:
        tok = TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        tok = ""
    if not tok and create:
        tok = secrets.token_urlsafe(18)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tok + "\n")
    return tok


def page_url(port, tok) -> str:
    return f"http://127.0.0.1:{port}/?t={tok}"


def shown_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(HERE))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- batches

def row_state(row):
    """'input' (waiting for the learner), 'marking' (waiting for the tutor) or 'closed'."""
    last = row["attempts"][-1]
    if last["text"] is None:
        return "input"
    return "marking" if last["mark"] is None else "closed"


def batch_status(batch):
    if batch["cancelled"]:
        return "cancelled"
    states = {row_state(r) for r in batch["rows"]}
    if "input" in states:
        return "open"
    return "answered" if "marking" in states else "done"


def batch_score(batch):
    """(right first try, right in the end, marked) over the rows with a marked first answer."""
    marked = [r for r in batch["rows"] if r["attempts"][0]["mark"]]
    first = sum(r["attempts"][0]["mark"]["ok"] for r in marked)
    final = sum(row_state(r) == "closed" and r["attempts"][-1]["mark"]["ok"] for r in marked)
    return first, final, len(marked)


def score_text(first, final, total, rewrites=True):
    text = f"{first}/{total} right first try"
    if rewrites and final != first:
        text += f" · {final}/{total} after rewriting"
    return text


# --------------------------------------------------------------------------- session

class Session:
    """One tutoring session: its items in order, mirrored to the day's notebook file."""

    def __init__(self, title, day):
        self.day = day
        self.title = ""
        self.items = []
        self.ended = False
        self.path = NOTEBOOK_DIR / f"{day}.md"
        try:
            existing = self.path.read_text()
        except FileNotFoundError:
            existing = ""
        self.prefix = existing.rstrip("\n") + "\n" if existing else f"# Notebook — {day}\n"
        self.number = sum(line.startswith("## Session ") for line in existing.splitlines()) + 1
        self.next_id = 1
        if title:
            self.set_title(title)

    def add(self, item):
        item["id"] = self.next_id
        self.next_id += 1
        self.items.append(item)
        return item

    def set_title(self, title):
        if title and title != self.title:
            self.title = title
            self.add({"kind": "title", "text": title})

    def latest_batch(self):
        return next((i for i in reversed(self.items) if i["kind"] == "batch"), None)

    def score(self):
        first = final = total = 0
        for item in self.items:
            if item["kind"] == "batch":
                f, g, t = batch_score(item)
                first, final, total = first + f, final + g, total + t
        return first, final, total

    def view(self):
        items = copy.deepcopy(self.items)
        for item in items:
            if item["kind"] == "batch":
                item["status"] = batch_status(item)
                item["score"] = batch_score(item)
        return {"title": self.title, "day": self.day, "session": self.number, "ended": self.ended,
                "items": items, "score": self.score()}

    # --- the notebook file ---
    def markdown(self):
        out = [f"## Session {self.number}", ""]
        for item in self.items:
            kind = item["kind"]
            if kind == "title":
                out += [f"### {item['text']}", ""]
            elif kind == "note":
                if item["title"]:
                    out += [f"#### {item['title']}", ""]
                out += [item["text"].strip(), ""]
            elif kind == "batch":
                out += [f"#### {item['title'] or 'Questions'}", ""]
                for n, row in enumerate(item["rows"], 1):
                    lines = []
                    for k, attempt in enumerate(row["attempts"]):
                        if attempt["text"] is None:
                            continue
                        mark = attempt["mark"]
                        text = attempt["text"] or "(no answer)"
                        if mark is None:
                            result = ""
                        elif mark["ok"]:
                            result = " ✓" + (f" ({mark['note']})" if mark["note"] else "")
                        else:
                            result = f" ✗ **{mark['correct']}**" + (f" — {mark['note']}" if mark["note"] else "")
                        lines.append(f"{n}. {row['prompt']} → {text}{result}" if k == 0
                                     else f"   - try {k + 1}: {text}{result}")
                    out += lines or [f"{n}. {row['prompt']} →"]
                first, final, total = batch_score(item)
                extra = []
                if item["cancelled"]:
                    extra.append("Answered in the terminal.")
                if total:
                    extra.append(score_text(first, final, total) + ".")
                if item["comment"]:
                    extra.append(item["comment"])
                out += ["", f"*{' '.join(extra)}*", ""] if extra else [""]
            elif kind == "summary":
                first, final, total = item["score"]
                out += [f"**Session score:** {score_text(first, final, total)}." if total
                        else "**Session score:** no marked answers.", ""]
        return "\n".join(out).rstrip("\n") + "\n"

    def save(self):
        if not any(i["kind"] != "title" for i in self.items):
            return                                  # nothing worth a file yet
        NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=NOTEBOOK_DIR, prefix=".tmp-", suffix=".md")
        with os.fdopen(fd, "w") as f:
            f.write(self.prefix + "\n" + self.markdown())
        os.replace(tmp, self.path)


class Notebook:
    """The current session, shared by the request threads. `version` changes on every update."""

    def __init__(self, title):
        self.cond = threading.Condition()
        self.version = 0
        self.session = Session(title, today())
        self.delivered = None      # (batch id, submission) that `watch` or `wait` confirmed printing
        self.stopping = False

    def _changed(self):
        self.version += 1
        self.session.save()
        self.cond.notify_all()

    def state(self):
        return {"version": self.version, **self.session.view()}

    def wait_change(self, since, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.version != since, timeout)
            return self.state()

    def _pending(self):
        """The latest batch if the learner sent something that wasn't printed yet."""
        batch = self.session.latest_batch()
        if batch and batch_status(batch) == "answered" and (batch["id"], batch["sent"]) != self.delivered:
            return batch
        return None

    def watch(self, timeout):
        """The next submission nobody printed yet; or `stopped` / `waiting`.

        It counts as printed only when the client confirms (`printed`): a killed watcher's request
        may still be waiting here, and what it takes must not be lost."""
        with self.cond:
            self.cond.wait_for(lambda: self.stopping or self._pending(), timeout)
            batch = self._pending()
            if batch:
                return {"status": "answered", "batch": self.batch_view(batch)}
            return {"status": "stopped" if self.stopping else "waiting"}

    def printed(self, batch_id, sent):
        with self.cond:
            self.delivered = (batch_id, sent)
            return {"ok": True}, None

    def stop(self):
        with self.cond:
            self.stopping = True
            self.cond.notify_all()

    def batch_view(self, batch):
        view = copy.deepcopy(batch)
        view["status"] = batch_status(batch)
        view["score"] = batch_score(batch)
        return view

    # --- updates; each returns (result, error) ---
    def new_session(self, title, day):
        with self.cond:
            self.session = Session(title, day)
            self.delivered = None
            self._changed()
            return {"session": self.session.number}, None

    def set_title(self, title):
        with self.cond:
            self.session.set_title(title)
            self._changed()
            return {"ok": True}, None

    def note(self, title, text):
        with self.cond:
            item = self.session.add({"kind": "note", "title": title, "text": text})
            self._changed()
            return {"id": item["id"]}, None

    def _withdraw_latest(self):
        batch = self.session.latest_batch()
        if batch and batch_status(batch) in ("open", "answered"):
            batch["cancelled"] = True
            return batch
        return None

    def ask(self, title, prompts):
        with self.cond:
            self._withdraw_latest()
            item = self.session.add({
                "kind": "batch", "title": title, "comment": "", "cancelled": False, "sent": 0,
                "rows": [{"prompt": p, "attempts": [{"text": None, "mark": None}]} for p in prompts]})
            self._changed()
            return {"id": item["id"]}, None

    def submit(self, batch_id, rows, answers):
        with self.cond:
            batch = self.session.latest_batch()
            if not batch or batch["id"] != batch_id or batch_status(batch) != "open":
                return None, "these questions are no longer open"
            open_rows = [i for i, r in enumerate(batch["rows"]) if row_state(r) == "input"]
            if rows != open_rows or len(answers) != len(rows):
                return None, "the page is out of date; reload it"
            for i, text in zip(rows, answers):
                batch["rows"][i]["attempts"][-1]["text"] = text
            batch["sent"] += 1
            self._changed()
            return {"ok": True}, None

    def wait_answer(self, batch_id, timeout):
        """The batch once it's no longer waiting for the learner, or None if it's gone."""
        def ready():
            batch = self.session.latest_batch()
            return not batch or batch["id"] != batch_id or batch_status(batch) != "open"
        with self.cond:
            self.cond.wait_for(ready, timeout)
            batch = self.session.latest_batch()
            if not batch or batch["id"] != batch_id:
                return {"status": "cancelled"}
            return {"status": batch_status(batch), "batch": self.batch_view(batch)}

    def feedback(self, marks, comment):
        with self.cond:
            batch = self.session.latest_batch()
            if not batch:
                return None, "there are no questions on the page"
            status = batch_status(batch)
            if status != "answered":
                return None, {"open": "the learner hasn't sent the answers yet",
                              "done": "everything in this batch is already marked",
                              "cancelled": "this batch was withdrawn"}[status]
            rows = [r for r in batch["rows"] if row_state(r) == "marking"]
            if len(marks) != len(rows):
                return None, f"batch {batch['id']} has {len(rows)} answers to mark, got {len(marks)} marks"
            for row, mark in zip(rows, marks):
                row["attempts"][-1]["mark"] = mark
                if not mark["ok"] and len(row["attempts"]) < MAX_TRIES:
                    row["attempts"].append({"text": None, "mark": None})
            if comment:
                batch["comment"] = comment
            self._changed()
            return self.batch_view(batch), None

    def cancel(self):
        with self.cond:
            batch = self._withdraw_latest()
            if not batch:
                return None, "no batch is waiting for answers"
            self._changed()
            return {"id": batch["id"]}, None

    def end(self):
        with self.cond:
            self.session.ended = True
            self.session.add({"kind": "summary", "score": self.session.score()})
            self._changed()
            return {"score": self.session.score(), "session": self.session.number,
                    "path": shown_path(self.session.path)}, None


# --------------------------------------------------------------------------- HTTP

def text_list(value):
    if not isinstance(value, list) or len(value) > MAX_PROMPTS or not all(isinstance(v, str) for v in value):
        return None
    return [v.strip()[:MAX_TEXT] for v in value]


def short_text(body, name, limit=MAX_TEXT):
    value = body.get(name, "")
    return value.strip()[:limit] if isinstance(value, str) else None


def parse_marks(value):
    if not isinstance(value, list):
        return None
    marks = []
    for m in value:
        if not (isinstance(m, dict) and isinstance(m.get("ok"), bool)
                and all(isinstance(m.get(k, ""), str) for k in ("correct", "note"))):
            return None
        marks.append({"ok": m["ok"], "correct": m.get("correct", "").strip()[:MAX_TEXT],
                      "note": m.get("note", "").strip()[:MAX_TEXT]})
    return marks


class Handler(BaseHTTPRequestHandler):
    server_version = "notebook"

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def fail(self, code, message):
        self.send(code, {"error": message})

    def reply(self, result):
        data, problem = result
        self.fail(409, problem) if problem else self.send(200, data)

    def host_ok(self):
        # Rejects DNS-rebinding requests that reach 127.0.0.1 under another name.
        host = self.headers.get("Host", "")
        return (host.rpartition(":")[0] or host) in ("127.0.0.1", "localhost")

    def token_ok(self, given):
        return bool(given) and hmac.compare_digest(given.encode(), self.server.token.encode())

    def do_GET(self):
        url = parse.urlsplit(self.path)
        query = parse.parse_qs(url.query)
        if not self.host_ok():
            return self.fail(403, "bad host")
        if url.path == "/":
            if not self.token_ok(query.get("t", [""])[0]):
                return self.send(403, b"Forbidden: open the link the tutor gave you.", "text/plain; charset=utf-8")
            return self.send(200, PAGE.encode(), "text/html; charset=utf-8")
        if not self.token_ok(self.headers.get("X-Notebook-Token", "")):
            return self.fail(403, "bad token")
        try:
            timeout = max(0.0, min(float(query.get("timeout", ["0"])[0]), SLICE))
            since = int(query.get("since", ["-1"])[0])
            batch_id = int(query.get("id", ["-1"])[0])
        except ValueError:
            return self.fail(400, "timeout, since and id must be numbers")
        nb = self.server.notebook
        if url.path == "/api/ping":
            return self.send(200, {"ok": True})
        if url.path == "/api/state":
            return self.send(200, nb.wait_change(since, timeout))
        if url.path == "/api/wait":
            return self.send(200, nb.wait_answer(batch_id, timeout))
        if url.path == "/api/watch":
            return self.send(200, nb.watch(timeout))
        self.fail(404, "not found")

    def do_POST(self):
        url = parse.urlsplit(self.path)
        if not self.host_ok():
            return self.fail(403, "bad host")
        if not self.token_ok(self.headers.get("X-Notebook-Token", "")):
            return self.fail(403, "bad token")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self.fail(400, "bad body")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.fail(400, "body must be JSON")
        if not isinstance(body, dict):
            return self.fail(400, "body must be a JSON object")
        nb = self.server.notebook
        title = short_text(body, "title")
        if title is None:
            return self.fail(400, "title must be text")

        if url.path == "/api/ask":
            prompts = text_list(body.get("prompts"))
            if not prompts or not all(prompts):
                return self.fail(400, f"need 1–{MAX_PROMPTS} non-empty prompts")
            return self.reply(nb.ask(title, prompts))
        if url.path == "/api/submit":
            answers = text_list(body.get("answers"))
            rows = body.get("rows")
            if (answers is None or not isinstance(body.get("id"), int) or not isinstance(rows, list)
                    or not all(isinstance(r, int) for r in rows)):
                return self.fail(400, "need id, rows and answers")
            return self.reply(nb.submit(body["id"], rows, answers))
        if url.path == "/api/feedback":
            marks = parse_marks(body.get("marks"))
            comment = short_text(body, "comment")
            if marks is None or comment is None:
                return self.fail(400, "need marks")
            return self.reply(nb.feedback(marks, comment))
        if url.path == "/api/note":
            text = short_text(body, "text", MAX_NOTE)
            if not text:
                return self.fail(400, "need the note's text")
            return self.reply(nb.note(title, text))
        if url.path == "/api/title":
            if not title:
                return self.fail(400, "need a title")
            return self.reply(nb.set_title(title))
        if url.path == "/api/session":
            day = body.get("day")
            try:
                day = date.fromisoformat(day).isoformat()
            except (TypeError, ValueError):
                return self.fail(400, "day must be YYYY-MM-DD")
            return self.reply(nb.new_session(title, day))
        if url.path == "/api/printed":
            if not (isinstance(body.get("id"), int) and isinstance(body.get("sent"), int)):
                return self.fail(400, "need id and sent")
            return self.reply(nb.printed(body["id"], body["sent"]))
        if url.path == "/api/cancel":
            return self.reply(nb.cancel())
        if url.path == "/api/end":
            return self.reply(nb.end())
        if url.path == "/api/stop":
            nb.stop()               # watchers get `stopped` and exit quietly
            self.send(200, {"ok": True})

            def shut_down():
                time.sleep(0.3)     # let the watchers' replies go out first
                self.server.shutdown()
            threading.Thread(target=shut_down, daemon=True).start()
            return
        self.fail(404, "not found")


class NotebookServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, token, title):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token
        self.notebook = Notebook(title)


# --------------------------------------------------------------------------- client

class NotRunning(Exception):
    pass


OPENER = request.build_opener(request.ProxyHandler({}))   # never send localhost through a proxy


def api(method, path, body=None, timeout=10.0):
    """Call the server; return (status, json). Raise NotRunning if it can't be reached."""
    tok = read_token()
    if not tok:
        raise NotRunning
    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                          headers={"X-Notebook-Token": tok, "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except error.HTTPError as e:
        with e:
            try:
                return e.code, json.loads(e.read())
            except json.JSONDecodeError:
                return e.code, {"error": f"HTTP {e.code}"}
    except (error.URLError, OSError, json.JSONDecodeError):
        raise NotRunning


def running() -> bool:
    try:
        return api("GET", "/api/ping", timeout=2)[0] == 200
    except NotRunning:
        return False


def call(method, path, body=None, timeout=10.0):
    try:
        code, data = api(method, path, body, timeout)
    except NotRunning:
        sys.exit(f"error: the notebook server isn't running on port {PORT} (start it with ./notebook.py start)")
    if code != 200:
        sys.exit(f"error: {data.get('error', f'HTTP {code}')}")
    return data


def print_answers(batch):
    rows = [(n, r) for n, r in enumerate(batch["rows"], 1) if row_state(r) == "marking"]
    rewrites = any(len(r["attempts"]) > 1 for _, r in rows)
    title = f": {batch['title']}" if batch["title"] else ""
    print(f"{'REWRITES' if rewrites else 'ANSWERS'} (batch {batch['id']}{title})")
    for n, row in rows:
        attempts = row["attempts"]
        line = f"{n}. {row['prompt']} → {attempts[-1]['text'] or '(no answer)'}"
        if len(attempts) > 1:
            before = attempts[-2]["text"] or "(no answer)"
            line += f"   (try {len(attempts)} of {MAX_TRIES}; before: {before}; correct: {attempts[-2]['mark']['correct']})"
        print(line)
    which = "all" if not rewrites else "item" + ("s" if len(rows) > 1 else "")
    print(f"Mark {which} {', '.join(str(n) for n, _ in rows)} in this order with ./notebook.py feedback.")


def show_answers(batch):
    """Print the answers to mark and tell the server they were printed."""
    print_answers(batch)
    sys.stdout.flush()
    try:
        api("POST", "/api/printed", {"id": batch["id"], "sent": batch["sent"]})
    except NotRunning:
        pass


def wait_for(batch_id, timeout):
    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        slice_ = min(SLICE, remaining)
        data = call("GET", f"/api/wait?id={batch_id}&timeout={slice_:.1f}", timeout=slice_ + 10)
        status = data["status"]
        if status == "answered":
            show_answers(data["batch"])
            return 0
        if status == "done":
            print(f"Batch {batch_id} is already marked; nothing to wait for.")
            return 0
        if status == "cancelled":
            print(f"Batch {batch_id} was withdrawn or replaced; no answers.")
            return 3
        if remaining <= 0:
            if timeout == 0:
                print(f"Batch {batch_id} is still waiting for the learner.")
                return 4
            print(f"Timed out after {timeout:g} s; batch {batch_id} is still open on the page.")
            return 2


def state():
    return call("GET", "/api/state")


def latest_batch(st):
    return next((i for i in reversed(st["items"]) if i["kind"] == "batch"), None)


# --------------------------------------------------------------------------- commands

def cmd_serve(args):
    tok = read_token(create=True)
    try:
        server = NotebookServer(args.port, tok, args.title.strip())
    except OSError as e:
        if running():
            print(f"Already running: {page_url(args.port, tok)}")
            return 0
        sys.exit(f"error: can't listen on 127.0.0.1:{args.port}: {e.strerror or e}")
    print(f"Notebook: {page_url(args.port, tok)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_start(args):
    tok = read_token(create=True)
    title = args.title.strip()
    if running():
        st = state()
        if st["day"] != today() or st["ended"]:
            call("POST", "/api/session", {"title": title, "day": today()})
            print(f"Notebook (already running, new session): {page_url(PORT, tok)}")
        else:
            if title:
                call("POST", "/api/title", {"title": title})
            print(f"Notebook (already running, same session): {page_url(PORT, tok)}")
        return 0
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", "--port", str(PORT),
                             "--title", title],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if running():
            proc.stderr.close()
            print(f"Notebook (started): {page_url(PORT, tok)}")
            return 0
        if proc.poll() is not None:
            sys.exit(proc.stderr.read().decode().strip() or "error: the notebook server exited")
        time.sleep(0.1)
    proc.kill()
    sys.exit("error: the notebook server didn't start")


def cmd_status(args):
    if not running():
        print(f"Not running (port {PORT}).")
        return 1
    st = state()
    print(f"Notebook: {page_url(PORT, read_token())}")
    print(f"Session {st['session']} ({st['day']}){': ' + st['title'] if st['title'] else ''}"
          f"{' — ended' if st['ended'] else ''}")
    batch = latest_batch(st)
    if batch:
        print(f"Latest batch {batch['id']}: {batch['status']} ({len(batch['rows'])} prompts)")
    first, final, total = st["score"]
    print(f"Score so far: {score_text(first, final, total)}" if total else "No marked answers yet.")
    return 0


def cmd_title(args):
    call("POST", "/api/title", {"title": args.text})
    print("Title set.")
    return 0


def cmd_note(args):
    text = sys.stdin.read() if args.text == "-" else args.text
    if not text.strip():
        sys.exit("error: the note is empty")
    call("POST", "/api/note", {"title": args.title, "text": text})
    print("Note posted.")
    return 0


def cmd_ask(args):
    prompts = [p.strip() for p in args.prompts]
    if not all(prompts) or len(prompts) > MAX_PROMPTS:
        sys.exit(f"error: need 1–{MAX_PROMPTS} non-empty prompts")
    batch_id = call("POST", "/api/ask", {"title": args.title, "prompts": prompts})["id"]
    if not args.wait:
        print(f"Batch {batch_id} is on the page ({len(prompts)} prompts).")
        return 0
    print(f"Batch {batch_id} is on the page ({len(prompts)} prompts). Waiting for the answers…", flush=True)
    return wait_for(batch_id, args.timeout)


def cmd_watch(args):
    # stdout is the event stream: only the learner's answers and a NOTEBOOK DOWN line go there.
    deadline = time.monotonic() + args.timeout if args.timeout else None
    misses = 0
    while True:
        slice_ = SLICE
        if deadline is not None:
            slice_ = min(SLICE, deadline - time.monotonic())
            if slice_ <= 0:
                return 2
        try:
            code, data = api("GET", f"/api/watch?timeout={slice_:.1f}", timeout=slice_ + 10)
        except NotRunning:
            misses += 1
            if misses < 3:
                time.sleep(1)
                continue
            print(f"NOTEBOOK DOWN: the server on port {PORT} isn't responding. "
                  "Run ./notebook.py start, then watch again.", flush=True)
            return 1
        misses = 0
        if code != 200:
            print(f"NOTEBOOK DOWN: {data.get('error', f'HTTP {code}')}", flush=True)
            return 1
        if data["status"] == "answered":
            show_answers(data["batch"])
        elif data["status"] == "stopped":
            return 0


def cmd_wait(args):
    batch = latest_batch(state())
    if not batch:
        sys.exit("error: there are no questions on the page")
    return wait_for(batch["id"], args.timeout)


def parse_mark(mark):
    m = mark.strip()
    if m.lower() == "ok":
        return {"ok": True, "correct": "", "note": ""}
    if m.lower().startswith("ok:"):
        return {"ok": True, "correct": "", "note": m[3:].strip()}
    correct, _, note = m.partition("|")
    if not correct.strip():
        sys.exit(f"error: bad mark '{mark}' (use ok, 'ok: NOTE', CORRECT or 'CORRECT | REASON')")
    return {"ok": False, "correct": correct.strip(), "note": note.strip()}


def cmd_feedback(args):
    marks = [parse_mark(m) for m in args.marks]
    batch = call("POST", "/api/feedback", {"marks": marks, "comment": args.comment})
    right = sum(m["ok"] for m in marks)
    reopened = [n for n, r in enumerate(batch["rows"], 1) if row_state(r) == "input"]
    if reopened:
        print(f"Marked {right}/{len(marks)} right. Rewrite fields are open for "
              f"{', '.join(map(str, reopened))}.", flush=True)
        if args.wait:
            return wait_for(batch["id"], args.timeout)
    else:
        first, final, total = batch["score"]
        print(f"Marked {right}/{len(marks)} right. Batch {batch['id']} is done: {score_text(first, final, total)}.")
    return 0


def cmd_cancel(args):
    batch_id = call("POST", "/api/cancel", {})["id"]
    print(f"Withdrew batch {batch_id}.")
    return 0


def cmd_end(args):
    data = call("POST", "/api/end", {})
    first, final, total = data["score"]
    if total:
        pct = round(100 * first / total)
        print(f"SESSION SCORE (session {data['session']}): {score_text(first, final, total, rewrites=False)} "
              f"({pct}%) · {final}/{total} after rewriting")
    else:
        print(f"SESSION SCORE (session {data['session']}): no marked answers")
    print(f"Notebook file: {data['path']}")
    return 0


def cmd_stop(args):
    try:
        api("POST", "/api/stop", {})
    except NotRunning:
        print("Not running.")
        return 0
    deadline = time.monotonic() + 5
    while running():
        if time.monotonic() > deadline:
            sys.exit("error: the notebook server didn't stop")
        time.sleep(0.1)
    print("Stopped.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="notebook.py", description="The Spanish tutor's notebook page.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the server in the foreground")
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--title", default="")
    s.set_defaults(func=cmd_serve)
    s = sub.add_parser("start", help="start the server in the background")
    s.add_argument("--title", default="")
    s.set_defaults(func=cmd_start)
    sub.add_parser("status", help="link, session and score").set_defaults(func=cmd_status)

    s = sub.add_parser("title", help="set the heading (lesson and topic)")
    s.add_argument("text")
    s.set_defaults(func=cmd_title)
    s = sub.add_parser("note", help="post a note")
    s.add_argument("--title", default="")
    s.add_argument("text")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("ask", help="post a batch (with --wait, wait for the answers)")
    s.add_argument("--title", default="")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--timeout", type=float, default=1200)
    s.add_argument("prompts", nargs="+")
    s.set_defaults(func=cmd_ask)
    s = sub.add_parser("watch", help="print the answers and rewrites as they're sent")
    s.add_argument("--timeout", type=float, default=1800)
    s.set_defaults(func=cmd_watch)
    s = sub.add_parser("wait", help="wait for the answers or rewrites of the latest batch")
    s.add_argument("--timeout", type=float, default=1200)
    s.set_defaults(func=cmd_wait)
    s = sub.add_parser("feedback", help="mark the answers (with --wait, wait for the rewrites)")
    s.add_argument("--comment", default="")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--timeout", type=float, default=1200)
    s.add_argument("marks", nargs="+")
    s.set_defaults(func=cmd_feedback)

    sub.add_parser("cancel", help="withdraw the latest batch").set_defaults(func=cmd_cancel)
    sub.add_parser("end", help="show and print the session score").set_defaults(func=cmd_end)
    sub.add_parser("stop", help="stop the server").set_defaults(func=cmd_stop)

    args = p.parse_args(argv)
    if getattr(args, "timeout", 0) < 0:
        sys.exit("error: --timeout can't be negative")
    return args.func(args)


# --------------------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notebook</title>
<style>
  :root {
    --bg: #faf8f4; --card: #ffffff; --text: #1f1d1a; --muted: #6d675e; --line: #e4dfd6;
    --accent: #b5482a; --accent-text: #ffffff; --ok: #2f7d4f; --ok-bg: #e8f4ec; --bad: #b3261e; --bad-bg: #fbeceb;
    --field: #ffffff; --note: #f6f1e7;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1b1a18; --card: #252320; --text: #ece8e1; --muted: #a39d93; --line: #3a3732;
      --accent: #e0805f; --accent-text: #1b1a18; --ok: #7cc79a; --ok-bg: #1f3427; --bad: #f08c84; --bad-bg: #3d2523;
      --field: #1f1d1b; --note: #2b2823;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width: 720px; margin: 0 auto; padding: 16px 16px 40vh; }
  #top { position: sticky; top: 0; z-index: 1; background: var(--bg); padding: 8px 0 12px;
         border-bottom: 1px solid var(--line); margin-bottom: 16px; }
  #top h1 { font-size: 22px; margin: 0; }
  #sub { font-size: 14px; color: var(--muted); display: flex; gap: 12px; flex-wrap: wrap; }
  #conn.off { color: var(--bad); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px 20px; margin: 0 0 16px; }
  .card h2 { font-size: 18px; margin: 0; }
  .card > header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap;
                   margin-bottom: 4px; }
  .card, .divider { scroll-margin-top: 96px; }
  .score { font-size: 15px; color: var(--muted); }
  .divider { font-size: 20px; margin: 28px 0 12px; padding-top: 4px; }
  .note { background: var(--note); }
  .note table { border-collapse: collapse; margin: 8px 0; }
  .note th, .note td { border: 1px solid var(--line); padding: 4px 10px; text-align: left; }
  .note p, .note ul, .note ol { margin: 8px 0; }
  .note code { font-size: 16px; }
  .muted { color: var(--muted); }
  ol.rows { list-style: none; margin: 0; padding: 0; }
  ol.rows > li { display: grid; grid-template-columns: 2em 1fr; gap: 2px 8px; padding: 10px 0; border-bottom: 1px solid var(--line); }
  ol.rows > li:last-child { border-bottom: 0; }
  .n { font-weight: 600; color: var(--muted); text-align: right; }
  .prompt { font-weight: 500; }
  .body { grid-column: 2; }
  .attempt { margin-top: 2px; }
  .try { font-size: 14px; color: var(--muted); margin-right: 6px; }
  .wrong { text-decoration: line-through; text-decoration-color: var(--bad); }
  .mark { display: inline-block; margin: 4px 0 0 6px; padding: 1px 8px; border-radius: 6px; font-size: 16px; }
  .mark.ok { background: var(--ok-bg); color: var(--ok); }
  .mark.bad { background: var(--bad-bg); color: var(--bad); }
  input[type=text] { width: 100%; margin-top: 6px; font: inherit; padding: 8px 10px; color: var(--text);
                     background: var(--field); border: 1px solid var(--line); border-radius: 8px; }
  input[type=text]:focus { outline: 2px solid var(--accent); outline-offset: 0; border-color: transparent; }
  .actions { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
  .send { font: inherit; font-weight: 600; white-space: nowrap; padding: 8px 20px; border: 0; border-radius: 8px;
          background: var(--accent); color: var(--accent-text); cursor: pointer; }
  .send:disabled { opacity: .5; cursor: default; }
  .foot { margin-top: 10px; }
  .error { color: var(--bad); }
  .summary { text-align: center; }
  .summary strong { font-size: 22px; display: block; }
</style>
</head>
<body>
<main>
  <div id="top"><h1 id="title">Notebook</h1><div id="sub"><span id="session"></span><span id="conn">connecting…</span></div></div>
  <div id="items"></div>
  <p id="empty" class="muted">The tutor’s notes and questions will appear here.</p>
</main>
<script>
"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const HEAD = {"X-Notebook-Token": TOKEN, "Content-Type": "application/json"};
const MAX_TRIES = 3;
const itemsEl = document.getElementById("items");
const rendered = new Map();   // item id -> {key, el}
let version = -1, sessionKey = null, firstLoad = true;

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null && k !== false) e.append(k);
  return e;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
function store(fn) { try { return fn(); } catch (e) { return null; } }

// --- a small, safe Markdown subset: paragraphs, lists, tables, **bold**, *italic*, `code` ---
function inline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(el("strong", {}, ...inline(t.slice(2, -2))));
    else if (t.startsWith("`")) out.push(el("code", {}, t.slice(1, -1)));
    else out.push(el("em", {}, ...inline(t.slice(1, -1))));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
function cells(line) { return line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()); }
function markdown(src) {
  const frag = document.createDocumentFragment();
  const blocks = src.replace(/\r/g, "").split(/\n\s*\n/);
  for (const block of blocks) {
    const lines = block.split("\n").filter(l => l.trim());
    if (!lines.length) continue;
    if (lines.every(l => l.trim().startsWith("|"))) {
      const table = el("table");
      const rows = lines.filter(l => !/^\s*\|?[\s:|-]+\|?\s*$/.test(l));
      const hasHead = lines.length > 1 && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[1]);
      rows.forEach((l, i) => {
        const tag = hasHead && i === 0 ? "th" : "td";
        table.append(el("tr", {}, ...cells(l).map(c => el(tag, {}, ...inline(c)))));
      });
      frag.append(table);
    } else if (lines.every(l => /^\s*[-*]\s+/.test(l))) {
      frag.append(el("ul", {}, ...lines.map(l => el("li", {}, ...inline(l.replace(/^\s*[-*]\s+/, ""))))));
    } else if (lines.every(l => /^\s*\d+[.)]\s+/.test(l))) {
      frag.append(el("ol", {}, ...lines.map(l => el("li", {}, ...inline(l.replace(/^\s*\d+[.)]\s+/, ""))))));
    } else if (lines.length === 1 && /^#+\s+/.test(lines[0])) {
      frag.append(el("h3", {}, ...inline(lines[0].replace(/^#+\s+/, ""))));
    } else {
      const p = el("p");
      lines.forEach((l, i) => { if (i) p.append(el("br")); p.append(...inline(l)); });
      frag.append(p);
    }
  }
  return frag;
}

function scoreText(score, done) {
  const [first, final, total] = score;
  if (!total) return "";
  let t = first + "/" + total + " right first try";
  if (final !== first && done) t += " · " + final + "/" + total + " after rewriting";
  return t;
}

// --- items ---
function renderItem(item) {
  if (item.kind === "title") return el("h2", {class: "divider"}, item.text);
  if (item.kind === "note") {
    return el("section", {class: "card note"}, item.title ? el("h2", {}, item.title) : null, markdown(item.text));
  }
  if (item.kind === "summary") {
    const [first, final, total] = item.score;
    return el("section", {class: "card summary"},
      el("div", {class: "muted"}, "Session score"),
      total ? el("strong", {}, first + " / " + total + " right first try") : el("strong", {}, "No marked answers"),
      total && final !== first ? el("div", {}, final + " / " + total + " after rewriting") : null);
  }
  return renderBatch(item);
}

function markEl(mark) {
  if (mark.ok) return el("span", {class: "mark ok"}, "✓" + (mark.note ? " " + mark.note : ""));
  return el("span", {class: "mark bad"}, "✗ ", el("strong", {}, mark.correct), mark.note ? " — " + mark.note : null);
}

function renderBatch(batch) {
  const open = batch.status === "open";
  const inputs = [];
  const card = el("section", {class: "card batch"});
  const draftKey = (row, k) => "nb-draft-" + batch.id + "-" + row + "-" + k;
  card.append(el("header", {}, el("h2", {}, batch.title || "Questions"),
    el("span", {class: "score"}, scoreText(batch.score, batch.status === "done"))));
  const list = el("ol", {class: "rows"});
  batch.rows.forEach((row, r) => {
    const body = el("div", {class: "body"});
    row.attempts.forEach((a, k) => {
      if (a.text === null) {
        if (!open) return;
        const input = el("input", {type: "text", lang: "es", autocomplete: "off", autocapitalize: "off",
          autocorrect: "off", spellcheck: "false", "aria-label": (k ? "Rewrite " : "Answer ") + (r + 1),
          placeholder: k ? "Write it again" + (k === MAX_TRIES - 1 ? " (last try)" : "") : ""});
        input.value = store(() => sessionStorage.getItem(draftKey(r, k))) || "";
        input.addEventListener("input", () => store(() => sessionStorage.setItem(draftKey(r, k), input.value)));
        input.dataset.row = r; input.dataset.k = k;
        inputs.push(input);
        body.append(input);
        return;
      }
      const line = el("div", {class: "attempt"});
      if (k) line.append(el("span", {class: "try"}, "try " + (k + 1)));
      line.append(a.text ? el("span", {class: a.mark && !a.mark.ok ? "wrong" : ""}, a.text)
                         : el("span", {class: "muted"}, "(no answer)"));
      if (a.mark) line.append(markEl(a.mark));
      body.append(line);
    });
    list.append(el("li", {}, el("span", {class: "n"}, (r + 1) + "."), el("span", {class: "prompt"}, row.prompt), body));
  });
  card.append(list);

  const foot = el("div", {class: "foot"});
  if (open) {
    const button = el("button", {type: "button", class: "send"}, "Send");
    const err = el("span", {class: "error"});
    const send = async () => {
      button.disabled = true; err.textContent = "";
      try {
        const res = await fetch("/api/submit", {method: "POST", headers: HEAD, body: JSON.stringify({
          id: batch.id, rows: inputs.map(i => Number(i.dataset.row)), answers: inputs.map(i => i.value)})});
        if (!res.ok) throw new Error((await res.json()).error || "HTTP " + res.status);
        inputs.forEach(i => store(() => sessionStorage.removeItem(draftKey(i.dataset.row, i.dataset.k))));
      } catch (e) { err.textContent = "Couldn’t send: " + e.message; button.disabled = false; }
    };
    button.addEventListener("click", send);
    inputs.forEach((input, i) => input.addEventListener("keydown", ev => {
      if (ev.key !== "Enter" || ev.isComposing) return;
      ev.preventDefault();
      if (i + 1 < inputs.length) inputs[i + 1].focus(); else send();
    }));
    foot.append(el("div", {class: "actions"}, button,
      el("span", {class: "muted"}, "Enter moves to the next field; on the last one it sends."), err));
  } else if (batch.status === "answered") {
    foot.append(el("p", {class: "muted"}, "Sent. The tutor is checking…"));
  } else if (batch.status === "cancelled") {
    foot.append(el("p", {class: "muted"}, "Answered in the terminal."));
  }
  if (batch.comment) foot.append(el("p", {}, ...inline(batch.comment)));
  card.append(foot);
  card.focusFirst = () => inputs.length && inputs[0].focus({preventScroll: true});
  return card;
}

function render(st) {
  document.getElementById("title").textContent = st.title || "Notebook";
  document.getElementById("session").textContent = "Session " + st.session + " · " + st.day;
  const key = st.day + "/" + st.session;
  if (key !== sessionKey) { sessionKey = key; rendered.clear(); itemsEl.replaceChildren(); }
  let added = null, asking = null;   // the last new item; a card that now waits for input
  const seen = new Set();
  for (const item of st.items) {
    seen.add(item.id);
    const k = JSON.stringify(item);
    const old = rendered.get(item.id);
    if (old && old.key === k) continue;
    const node = renderItem(item);
    if (old) old.el.replaceWith(node); else { itemsEl.append(node); added = node; }
    rendered.set(item.id, {key: k, el: node});
    if (node.querySelector && node.querySelector("input")) asking = node;
  }
  for (const [id, r] of rendered) if (!seen.has(id)) { r.el.remove(); rendered.delete(id); }
  document.getElementById("empty").hidden = st.items.length > 0;
  const waiting = st.items.some(i => i.kind === "batch" && i.status === "open");
  document.title = (waiting ? "● " : "") + (st.title || "Notebook");
  if (firstLoad) {
    window.scrollTo(0, document.body.scrollHeight);
    const open = [...itemsEl.children].reverse().find(n => n.querySelector && n.querySelector("input"));
    if (open) { open.scrollIntoView({block: "start"}); open.focusFirst(); }
  } else if (asking) {
    asking.scrollIntoView({behavior: "smooth", block: "start"});
    asking.focusFirst();
  } else if (added) {
    added.scrollIntoView({behavior: "smooth", block: "start"});
  }
  firstLoad = false;
}

function setConn(ok) {
  const c = document.getElementById("conn");
  c.textContent = ok ? "" : "can’t reach the tutor — retrying…";
  c.className = ok ? "" : "off";
}

async function loop() {
  for (;;) {
    try {
      const r = await fetch("/api/state?since=" + version + "&timeout=25", {headers: HEAD});
      if (r.status === 403) {
        setConn(false);
        itemsEl.replaceChildren(el("p", {}, "This link is out of date. Ask the tutor for the notebook link."));
        return;
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      const st = await r.json();
      setConn(true);
      version = st.version;
      render(st);
    } catch (e) {
      setConn(false);
      await sleep(2000);
    }
  }
}
loop();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
