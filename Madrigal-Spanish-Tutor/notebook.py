#!/usr/bin/env python3
"""The tutor's notebook: a local web page beside the terminal, where the learner answers batches of
prompts (each in its own numbered field), rewrites what they got wrong, and finds the tutor's notes.

The whole session stays on the page and is saved to learner/notebook/YYYY-MM-DD.html: the same page,
read-only, with every session of the day, to open in a browser later.

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
import base64
import copy
import hashlib
import hmac
import json
import os
import re
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
        self.path = NOTEBOOK_DIR / f"{day}.html"
        self.earlier = read_saved(self.path)          # the day's earlier sessions, from the file
        self.number = max((s["number"] for s in self.earlier), default=0) + 1
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
    def save(self):
        if not any(i["kind"] != "title" for i in self.items):
            return                                  # nothing worth a file yet
        sessions = self.earlier + [{"number": self.number, "items": self.view()["items"]}]
        NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=NOTEBOOK_DIR, prefix=".tmp-", suffix=".html")
        with os.fdopen(fd, "w") as f:
            f.write(saved_page(self.day, sessions))
        os.replace(tmp, self.path)


SAVED_RE = re.compile(r'<script type="application/json" id="saved">(.*?)</script>', re.S)


def saved_page(day, sessions):
    """The notebook file: the page in read-only mode, with the sessions embedded as JSON."""
    data = json.dumps({"day": day, "sessions": sessions}, ensure_ascii=False)
    # Inside the JSON, < > & only occur in strings, where these escapes mean the same thing; without
    # them the text can't close the <script> element.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    script = PAGE.split("<script>", 1)[1].split("</script>", 1)[0]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp = (f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
           f'script-src \'sha256-{digest}\'; style-src \'unsafe-inline\'; img-src data:">')
    page = PAGE.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + csp, 1)
    return page.replace("<script>", f'<script type="application/json" id="saved">{data}</script>\n<script>', 1)


def read_saved(path):
    """The sessions stored in a notebook file ([] if there's none). An unreadable file is moved aside."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    m = SAVED_RE.search(text)
    try:
        sessions = json.loads(m.group(1))["sessions"]
        if all(isinstance(x, dict) and isinstance(x.get("number"), int) and isinstance(x.get("items"), list)
               for x in sessions):
            return sessions
    except (AttributeError, ValueError, KeyError, TypeError):
        pass
    aside = path.with_name(f"{path.stem}-unreadable-{int(time.time())}{path.suffix}")
    path.rename(aside)
    print(f"warning: couldn't read {shown_path(path)}; moved it to {aside.name}", file=sys.stderr)
    return []


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
                             "img-src data:; connect-src 'self'; frame-ancestors 'none'")
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

# The Aurora Polaris mark: the rays' path from ../assets/logo/symbol-small.svg (the same path is in
# tile-small.svg). Those files are generated in the logo repository; when they change, copy the new
# path here and don't edit it by hand. The page colours it with --ray-* (deep set on light, bright on dark).
LOGO_PATH = ("M10.00 194.71L15.50 96.21A4.00 4.00 0 0 1 23.50 96.21L29.00 194.71A9.50 9.50 0 0 1 10.00 194.71Z"
             "M31.70 217.69L37.20 110.54A4.00 4.00 0 0 1 45.20 110.54L50.70 217.69A9.50 9.50 0 0 1 31.70 217.69Z"
             "M53.40 227.74L58.90 112.78A4.00 4.00 0 0 1 66.90 112.78L72.40 227.74A9.50 9.50 0 0 1 53.40 227.74Z"
             "M75.10 221.01L80.60 99.86A4.00 4.00 0 0 1 88.60 99.86L94.10 221.01A9.50 9.50 0 0 1 75.10 221.01Z"
             "M96.80 200.08L102.30 74.95A4.00 4.00 0 0 1 110.30 74.95L115.80 200.08A9.50 9.50 0 0 1 96.80 200.08Z"
             "M118.50 172.94L124.00 46.44A4.00 4.00 0 0 1 132.00 46.44L137.50 172.94A9.50 9.50 0 0 1 118.50 172.94Z"
             "M140.20 149.96L145.70 24.83A4.00 4.00 0 0 1 153.70 24.83L159.20 149.96A9.50 9.50 0 0 1 140.20 149.96Z"
             "M161.90 139.92L167.40 18.76A4.00 4.00 0 0 1 175.40 18.76L180.90 139.92A9.50 9.50 0 0 1 161.90 139.92Z"
             "M183.60 146.64L189.10 31.69A4.00 4.00 0 0 1 197.10 31.69L202.60 146.64A9.50 9.50 0 0 1 183.60 146.64Z"
             "M205.30 167.57L210.80 60.42A4.00 4.00 0 0 1 218.80 60.42L224.30 167.57A9.50 9.50 0 0 1 205.30 167.57Z"
             "M227.00 194.71L232.50 96.21A4.00 4.00 0 0 1 240.50 96.21L246.00 194.71A9.50 9.50 0 0 1 227.00 194.71Z")

# The favicon: ../assets/logo/tile-small.svg (the mark on its Night tile), as a data: URI.
FAVICON = ("data:image/svg+xml," + parse.quote(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 256 256'><defs><linearGradient id='g' "
    "gradientUnits='userSpaceOnUse' x1='0' y1='237.2' x2='0' y2='14.8'><stop offset='0' stop-color='#2BD4C0'/>"
    "<stop offset='0.45' stop-color='#8B6CF0'/><stop offset='1' stop-color='#FF5C8A'/></linearGradient></defs>"
    "<rect width='256' height='256' rx='56' fill='#0A0818'/>"
    "<g transform='translate(128 124) scale(0.8) translate(-128 -126.0)'>"
    f"<path fill='url(#g)' d='{LOGO_PATH}'/></g></svg>", safe=" /:=',()-."))

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notebook</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
<style>
  /* An exercise book in warm monochrome. Colour is scarce: the logo, one accent (Send, focus) and
     the teacher's two inks: sage for right (✓) and rose for corrections (✗, the margin line).
     Everything else is neutral.
     The logo uses the deep set on light and the bright set on dark (assets/logo/GUIDELINES.md). */
  :root {
    --ray-base: #0E9686; --ray-mid: #6A48D8; --ray-tip: #D9366A;
    --bg: #fbfbfa; --fg: #1f1e1d; --muted: #696864; --border: #e9e8e6; --input-line: #8f8e8a;
    --accent: #6A48D8; --on-accent: #ffffff; --correction: #B42E4F; --right: #4A7656; --margin: rgba(180, 46, 79, .35);
    --m: 3.5rem; --gap: 1.1rem; --inset: calc(var(--m) + var(--gap));
    --serif: Charter, "Iowan Old Style", "Palatino Linotype", Palatino, "Noto Serif", "Droid Serif", Georgia, serif;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --sheet: linear-gradient(var(--margin), var(--margin)) no-repeat var(--m) 0 / 1px 100%;
    font-size: 19px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ray-base: #2BD4C0; --ray-mid: #8B6CF0; --ray-tip: #FF5C8A;
      --bg: #191918; --fg: #ebeae8; --muted: #9d9c98; --border: #2d2c2a; --input-line: #71706c;
      --accent: #9d85f2; --on-accent: #191918; --correction: #f0849b; --right: #8DC09B; --margin: rgba(240, 132, 155, .35);
    }
  }
  * { box-sizing: border-box; }
  html { background: var(--bg); scroll-padding-top: 6.5rem; }
  body { margin: 0; color: var(--fg); font: 1rem/1.6 var(--serif); }
  main { max-width: calc(var(--inset) + 34rem + 1.5rem); min-height: 100vh; margin: 0 auto;
         padding: 0 1.5rem 40vh 0; background: var(--sheet); }

  #top { position: sticky; top: 0; z-index: 1; display: grid; grid-template-columns: var(--m) 1fr;
         column-gap: var(--gap); align-items: center; padding: 1.2rem 0 .9rem; margin-bottom: 1.5rem;
         background: var(--sheet), var(--bg); box-shadow: 0 1px 0 var(--border); }
  #logo { justify-self: end; width: 28px; height: 28px; margin-right: .7rem; }
  #logo stop:nth-child(1) { stop-color: var(--ray-base); }
  #logo stop:nth-child(2) { stop-color: var(--ray-mid); }
  #logo stop:nth-child(3) { stop-color: var(--ray-tip); }
  #top h1 { font-size: 1.3rem; line-height: 1.25; font-weight: 600; margin: 0; }
  #sub { font: .72rem/1.5 var(--sans); color: var(--muted); display: flex; gap: .75rem; flex-wrap: wrap; }
  #conn.off { color: var(--correction); }

  #items, #empty { padding-left: var(--inset); }
  #items > * { margin: 0 0 2.75rem; }
  #items h2 { font-size: 1.1rem; line-height: 1.35; font-weight: 600; margin: 0 0 .35rem; }
  #items h2.divider { font-size: 1.45rem; line-height: 1.25; margin: 3.5rem 0 1.5rem; }
  #items h2.divider:first-child, #items h2.session + h2.divider { margin-top: 0; }
  #items h2.session { font-size: 1.45rem; line-height: 1.25; margin: 4rem 0 1.75rem calc(-1 * var(--inset));
                      padding: 1.5rem 0 0 var(--inset); border-top: 1px solid var(--border); }
  #items h2.session:first-child { margin-top: 0; padding-top: 0; border-top: 0; }
  .muted { color: var(--muted); }

  .note p, .note ul, .note ol { margin: .45rem 0; }
  .note ul, .note ol { padding-left: 1.2em; }
  .note h3 { font-size: 1rem; font-weight: 600; margin: 1rem 0 .2rem; }
  .note code { font: .85em/1 ui-monospace, "DejaVu Sans Mono", monospace; }
  .table { overflow-x: auto; margin: .6rem 0; }
  .note table { border-collapse: collapse; }
  .note th, .note td { text-align: left; vertical-align: top; padding: .25rem 1.4rem .25rem 0;
                       border-bottom: 1px solid var(--border); }
  .note th { font-weight: 600; }

  .batch > header { display: flex; justify-content: space-between; align-items: baseline; gap: .25rem 1rem;
                    flex-wrap: wrap; }
  .score { font: .72rem/1.5 var(--sans); color: var(--muted); }
  ol.rows { list-style: none; margin: 0; padding: 0; }
  ol.rows > li { position: relative; padding: .55rem 0; }
  .n { position: absolute; left: calc(-1 * var(--inset)); width: var(--m); padding-right: .7rem;
       text-align: right; font: .78rem/1.6rem var(--sans); color: var(--muted); white-space: nowrap; }
  .state { font: 600 .95rem/1 var(--sans); margin-right: .3rem; }
  .state.ok { color: var(--right); }
  .state.bad { color: var(--correction); }
  .prompt { display: block; color: var(--muted); }   /* the printed question; the answer is the strong text */
  .try { font: .7rem/1 var(--sans); color: var(--muted); margin-right: .4rem; }
  .wrong { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--correction);
           text-decoration-thickness: 1.5px; }
  .fix { color: var(--correction); margin-left: .6rem; }
  .fix strong { font-weight: 600; }
  .why { font-style: italic; margin-left: .45rem; }
  .good { color: var(--right); font-style: italic; margin-left: .5rem; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

  input[type=text] { display: block; width: 100%; margin-top: .15rem; padding: .1rem 0 .2rem; font: inherit;
                     color: var(--fg); background: transparent; border: 0; border-bottom: 1px solid var(--input-line);
                     border-radius: 0; }
  input[type=text]::placeholder { color: var(--muted); font-style: italic; opacity: 1; }
  input[type=text]:focus { outline: none; border-bottom-color: var(--accent); box-shadow: 0 1px 0 var(--accent); }

  .foot > p { margin: .8rem 0 0; }
  .actions { display: flex; align-items: center; gap: .5rem 1rem; margin-top: 1.1rem; flex-wrap: wrap;
             font: .72rem/1.5 var(--sans); }
  .send { font: 600 .8rem/1 var(--sans); white-space: nowrap; padding: .65rem 1.2rem; border: 0; border-radius: 6px;
          background: var(--accent); color: var(--on-accent); cursor: pointer; }
  .send:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .send:disabled { opacity: .5; cursor: default; }
  .error { color: var(--correction); }
  .grade { font-size: 1.5rem; line-height: 1.3; font-weight: 600; margin: .2rem 0 0; }
  .grade + p { margin: .2rem 0 0; color: var(--muted); }

  @media (max-width: 480px) {
    :root { --m: 2.5rem; --gap: .8rem; font-size: 18px; }
    main { padding-right: 1rem; }
    #logo { width: 24px; height: 24px; margin-right: .5rem; }
  }
</style>
</head>
<body>
<main>
  <div id="top">
    <svg id="logo" viewBox="0 0 256 256" aria-hidden="true" focusable="false"><defs><linearGradient id="rays"
      gradientUnits="userSpaceOnUse" x1="0" y1="237.2" x2="0" y2="14.8"><stop offset="0"/><stop offset="0.45"/>
      <stop offset="1"/></linearGradient></defs><path fill="url(#rays)" d="__LOGO_PATH__"/></svg>
    <div><h1 id="title">Notebook</h1><div id="sub"><span id="session"></span><span id="conn" role="status">connecting…</span></div></div>
  </div>
  <div id="items"></div>
  <p id="empty" class="muted">The tutor’s notes and questions will appear here.</p>
</main>
<script>
"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const HEAD = {"X-Notebook-Token": TOKEN, "Content-Type": "application/json"};
const MAX_TRIES = 3;
const SAVED = document.getElementById("saved");   // set in a saved notebook file: read-only
const itemsEl = document.getElementById("items");
const rendered = new Map();   // item id -> {key, el}
let version = -1, sessionKey = null, firstLoad = true;
const SMOOTH = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

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
      frag.append(el("div", {class: "table"}, table));
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
  let t = first + " of " + total + " right first try";
  if (final !== first && done) t += ", " + final + " of " + total + " after rewriting";
  return t;
}

// --- items ---
function renderItem(item) {
  if (item.kind === "title") return el("h2", {class: "divider"}, item.text);
  if (item.kind === "note") {
    return el("section", {class: "note"}, item.title ? el("h2", {}, item.title) : null, markdown(item.text));
  }
  if (item.kind === "summary") {
    const [first, final, total] = item.score;
    return el("section", {class: "summary"}, el("h2", {}, "Session score"),
      el("p", {class: "grade"}, total ? first + " of " + total + " right first try" : "No marked answers"),
      total && final !== first ? el("p", {}, final + " of " + total + " after rewriting") : null);
  }
  return renderBatch(item);
}

// A mark written after the answer, in the teacher's ink. The row's ✓ or ✗ goes in the margin.
function markEl(mark, k) {
  if (mark.ok) return mark.note || k ? el("span", {class: "good"}, "✓" + (mark.note ? " " + mark.note : "")) : null;
  return el("span", {class: "fix"}, el("strong", {}, mark.correct), mark.note ? el("span", {class: "why"}, mark.note) : null);
}
function stateEl(row) {
  const last = row.attempts.filter(a => a.text !== null).pop();
  if (!last || !last.mark) return null;
  return el("span", {class: "state " + (last.mark.ok ? "ok" : "bad")},
    el("span", {"aria-hidden": "true"}, last.mark.ok ? "✓" : "✗"), el("span", {class: "sr"}, last.mark.ok ? "right" : "wrong"));
}

function renderBatch(batch) {
  const open = batch.status === "open" && !SAVED;
  const inputs = [];
  const card = el("section", {class: "batch"});
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
          autocorrect: "off", spellcheck: "false", "aria-label": (k ? "Rewrite " : "Answer ") + (r + 1) + ": " + row.prompt,
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
      const m = a.mark && markEl(a.mark, k);
      if (m) line.append(m);
      body.append(line);
    });
    list.append(el("li", {}, el("span", {class: "n"}, stateEl(row), (r + 1) + "."),
      el("span", {class: "prompt"}, row.prompt), body));
  });
  card.append(list);

  const foot = el("div", {class: "foot"});
  if (open) {
    const button = el("button", {type: "button", class: "send"}, "Send");
    const err = el("span", {class: "error", role: "status"});
    const send = async () => {
      button.disabled = true; button.textContent = "Sending…"; err.textContent = "";
      try {
        const res = await fetch("/api/submit", {method: "POST", headers: HEAD, body: JSON.stringify({
          id: batch.id, rows: inputs.map(i => Number(i.dataset.row)), answers: inputs.map(i => i.value)})});
        if (!res.ok) throw new Error((await res.json()).error || "HTTP " + res.status);
        inputs.forEach(i => store(() => sessionStorage.removeItem(draftKey(i.dataset.row, i.dataset.k))));
      } catch (e) {
        err.textContent = "Couldn’t send: " + e.message;
        button.disabled = false; button.textContent = "Send";
      }
    };
    button.addEventListener("click", send);
    inputs.forEach((input, i) => input.addEventListener("keydown", ev => {
      if (ev.key !== "Enter" || ev.isComposing) return;
      ev.preventDefault();
      if (i + 1 < inputs.length) inputs[i + 1].focus(); else send();
    }));
    foot.append(el("div", {class: "actions"}, button,
      el("span", {class: "muted"}, "Enter goes to the next line. On the last line it sends."), err));
  } else if (SAVED && batch.status === "open") {
    foot.append(el("p", {class: "muted"}, "Not answered."));
  } else if (batch.status === "answered") {
    foot.append(el("p", {class: "muted"}, SAVED ? "Not marked." : "Sent. The tutor is checking…"));
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
  document.getElementById("session").textContent = "Session " + st.session + ", " + st.day;
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
    asking.scrollIntoView({behavior: SMOOTH, block: "start"});
    asking.focusFirst();
  } else if (added) {
    added.scrollIntoView({behavior: SMOOTH, block: "start"});
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
function showSaved(data) {
  const name = "Notebook, " + data.day;
  document.title = name;
  document.getElementById("title").textContent = name;
  document.getElementById("conn").hidden = true;
  document.getElementById("session").textContent =
    data.sessions.length + (data.sessions.length === 1 ? " session" : " sessions");
  for (const s of data.sessions) {
    itemsEl.append(el("h2", {class: "session"}, "Session " + s.number));
    for (const item of s.items) itemsEl.append(renderItem(item));
  }
  document.getElementById("empty").hidden = data.sessions.length > 0;
}

if (SAVED) showSaved(JSON.parse(SAVED.textContent)); else loop();
</script>
</body>
</html>
""".replace("__LOGO_PATH__", LOGO_PATH).replace("__FAVICON__", FAVICON)

if __name__ == "__main__":
    sys.exit(main())
