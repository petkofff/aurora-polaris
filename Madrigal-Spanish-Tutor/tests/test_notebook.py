"""Tests for notebook.py: the server, the tutor's commands, the page's API and the notebook file.

Each class runs its own server on a free port, with the token file and the notebook folder in a
temporary folder (NOTEBOOK_PORT, NOTEBOOK_TOKEN_FILE, NOTEBOOK_DIR) and a fixed date
(NOTEBOOK_TODAY), so the tests never touch a running notebook, .notebook-token or learner/.
"""
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib import error, parse, request

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "notebook.py"
LOGO = REPO.parent / "assets" / "logo"
REAL_TOKEN = REPO / ".notebook-token"
REAL_NOTEBOOK = REPO / "learner" / "notebook"
TODAY = "2026-10-31"
OPENER = request.build_opener(request.ProxyHandler({}))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fingerprint():
    """Hashes of the real token and notebook files, to check that the tests leave them alone."""
    paths = [REAL_TOKEN, *sorted(REAL_NOTEBOOK.glob("*"))] if REAL_NOTEBOOK.exists() else [REAL_TOKEN]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


class NotebookCase(unittest.TestCase):
    """Starts one server per class (unless serve = False)."""

    serve = True

    @classmethod
    def setUpClass(cls):
        cls._real = fingerprint()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.port = free_port()
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith("NOTEBOOK_")}
        cls.env.update(NOTEBOOK_PORT=str(cls.port), NOTEBOOK_TOKEN_FILE=str(cls.tmp / "token"),
                       NOTEBOOK_DIR=str(cls.tmp / "notebook"), NOTEBOOK_TODAY=TODAY)
        cls.server = None
        if cls.serve:
            cls.start_server()

    @classmethod
    def start_server(cls, *args):
        cls.server = subprocess.Popen([sys.executable, str(SCRIPT), "serve", *args], env=cls.env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if cls.run_nb("status").returncode == 0:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("notebook server didn't start")
        cls.token = Path(cls.env["NOTEBOOK_TOKEN_FILE"]).read_text().strip()

    @classmethod
    def stop_server(cls):
        if cls.server:
            cls.server.terminate()
            cls.server.wait(10)
            cls.server = None

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls._tmp.cleanup()
        if fingerprint() != cls._real:
            raise AssertionError(f"{cls.__name__} changed .notebook-token or learner/notebook/")

    def setUp(self):
        if self.server:
            batch = self.latest()
            if batch and batch["status"] in ("open", "answered"):
                self.ok("cancel")

    # --- running the script ---
    @classmethod
    def run_nb(cls, *args, stdin=None, timeout=30, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env or cls.env, capture_output=True,
                              text=True, input=stdin, timeout=timeout)

    def ok(self, *args, **kw) -> str:
        r = self.run_nb(*args, **kw)
        self.assertEqual(r.returncode, 0, f"notebook.py {args} failed:\n{r.stdout}{r.stderr}")
        return r.stdout

    def fails(self, *args, code=1) -> str:
        r = self.run_nb(*args)
        self.assertEqual(r.returncode, code, f"notebook.py {args}: expected exit {code}, got {r.returncode}\n"
                                             f"stdout: {r.stdout}\nstderr: {r.stderr}")
        return r.stdout + r.stderr

    def background(self, *args):
        """Run a waiting command (`ask --wait`, `wait`, `watch`) in the background."""
        proc = subprocess.Popen([sys.executable, str(SCRIPT), *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def reap():
            if proc.poll() is None:
                proc.kill()
            proc.communicate()
        self.addCleanup(reap)
        return proc

    def start_ask(self, *args):
        """Run `ask --wait` in the background; return the process once its batch is open on the page."""
        before = self.state()["version"]
        proc = self.background("ask", "--wait", *args)
        for _ in range(100):
            st = self.state()
            if st["version"] != before and self.latest(st) and self.latest(st)["status"] == "open":
                return proc
            time.sleep(0.05)
        raise AssertionError("ask didn't put a batch on the page")

    def read_event(self, proc, timeout=15):
        """The lines a running `watch` prints for one submission (up to its "Mark …" line)."""
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        lines = []
        try:
            while not lines or not lines[-1].startswith("Mark "):
                line = proc.stdout.readline()
                if not line:
                    raise AssertionError(f"watch ended without an event: {lines}")
                lines.append(line)
        finally:
            timer.cancel()
        return "".join(lines)

    def finish(self, proc, code=0):
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, code, out + err)
        return out

    # --- talking to the server like the page does ---
    def http(self, method, path, body=None, token=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token is not False:
            h["X-Notebook-Token"] = token or self.token
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=h)
        try:
            with OPENER.open(req, timeout=40) as r:
                return r.status, r.read()
        except error.HTTPError as e:
            with e:
                return e.code, e.read()

    def state(self):
        code, body = self.http("GET", "/api/state")
        self.assertEqual(code, 200)
        return json.loads(body)

    def latest(self, st=None):
        st = st or self.state()
        return next((i for i in reversed(st["items"]) if i["kind"] == "batch"), None)

    def submit(self, answers, rows=None, batch_id=None):
        batch = self.latest()
        if rows is None:
            rows = [i for i, r in enumerate(batch["rows"]) if r["attempts"][-1]["text"] is None]
        body = {"id": batch_id if batch_id is not None else batch["id"], "rows": rows, "answers": answers}
        return self.http("POST", "/api/submit", body)[0]

    def notebook_path(self):
        return Path(self.env["NOTEBOOK_DIR"]) / f"{TODAY}.html"

    def saved(self):
        """The data embedded in today's notebook file."""
        text = self.notebook_path().read_text()
        m = re.search(r'<script type="application/json" id="saved">(.*?)</script>', text, re.S)
        self.assertIsNotNone(m, "no saved data in the notebook file")
        data = json.loads(m.group(1))
        self.assertEqual(data["day"], TODAY)
        return data

    def saved_texts(self, session):
        return [i.get("text") for i in session["items"] if i["kind"] in ("title", "note")]


class TestAccess(NotebookCase):
    def test_page_needs_the_token(self):
        code, body = self.http("GET", f"/?t={self.token}", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"<title>Notebook</title>", body)
        self.assertEqual(self.http("GET", "/", token=False)[0], 403)
        self.assertEqual(self.http("GET", "/?t=wrong", token=False)[0], 403)

    def test_the_page_shows_the_logo_from_the_assets(self):
        # The page copies the mark and the favicon from assets/logo/; a new logo there must be copied too.
        page = self.http("GET", f"/?t={self.token}", token=False)[1].decode()
        path = re.search(r' d="([^"]+)"', (LOGO / "symbol-small.svg").read_text()).group(1)
        self.assertEqual(re.search(r' d="([^"]+)"', (LOGO / "tile-small.svg").read_text()).group(1), path)
        self.assertIn(f'<path fill="url(#rays)" d="{path}"/>', page)
        icon = re.search(r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml,([^"]+)">', page)
        tile = (LOGO / "tile-small.svg").read_text().replace('"', "'")
        self.assertEqual(parse.unquote(icon.group(1)), re.sub(r"<title>.*?</title>", "", tile).strip())
        with OPENER.open(f"http://127.0.0.1:{self.port}/?t={self.token}", timeout=10) as r:
            csp = r.headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("img-src data:;", csp)

    def test_api_needs_the_token(self):
        self.assertEqual(self.http("GET", "/api/state", token=False)[0], 403)
        self.assertEqual(self.http("GET", "/api/state", token="wrong")[0], 403)
        self.assertEqual(self.http("POST", "/api/note", {"text": "x"}, token="wrong")[0], 403)

    def test_other_host_names_are_rejected(self):
        self.assertEqual(self.http("GET", f"/?t={self.token}", token=False, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.http("GET", "/api/state", headers={"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.http("GET", "/api/state", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_bad_requests(self):
        self.assertEqual(self.http("POST", "/api/ask", {"prompts": []})[0], 400)
        self.assertEqual(self.http("POST", "/api/ask", {"prompts": ["ok", " "]})[0], 400)
        self.assertEqual(self.http("POST", "/api/ask", {"prompts": "the train"})[0], 400)
        self.assertEqual(self.http("POST", "/api/ask", {"prompts": ["x"] * 31})[0], 400)
        self.assertEqual(self.http("POST", "/api/ask", {"prompts": ["x"], "title": 5})[0], 400)
        self.assertEqual(self.http("POST", "/api/note", {"text": "  "})[0], 400)
        self.assertEqual(self.http("POST", "/api/session", {"day": "yesterday"})[0], 400)
        self.assertEqual(self.http("GET", "/api/state?since=abc")[0], 400)
        self.assertEqual(self.http("POST", "/api/printed", {"id": "1"})[0], 400)
        self.assertEqual(self.http("GET", "/nothing")[0], 404)


class TestAnswers(NotebookCase):
    def test_answers_are_printed_by_number(self):
        proc = self.start_ask("--title", "Into Spanish", "the train", "I took", "the soup")
        batch = self.latest()
        self.assertEqual([r["prompt"] for r in batch["rows"]], ["the train", "I took", "the soup"])
        self.assertEqual(self.submit(["el tren ", "tomé", ""]), 200)
        self.assertIn(f"ANSWERS (batch {batch['id']}: Into Spanish)\n"
                      "1. the train → el tren\n"
                      "2. I took → tomé\n"
                      "3. the soup → (no answer)\n"
                      "Mark all 1, 2, 3 in this order", self.finish(proc))
        self.assertEqual(self.latest()["status"], "answered")

    def test_page_long_poll_wakes_on_a_change(self):
        since = self.state()["version"]
        result = {}

        def poll():
            result["state"] = json.loads(self.http("GET", f"/api/state?since={since}&timeout=20")[1])

        t = threading.Thread(target=poll)
        start = time.monotonic()
        t.start()
        time.sleep(0.3)
        self.ok("note", "Hola")
        t.join(20)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result["state"]["items"][-1]["text"], "Hola")

    def test_submit_rules(self):
        self.start_ask("one", "two")
        batch_id = self.latest()["id"]
        self.assertEqual(self.submit(["uno"], rows=[0]), 409)                       # not every open row
        self.assertEqual(self.submit(["uno"], rows=[0, 1]), 409)                    # answers ≠ rows
        self.assertEqual(self.submit(["uno", "dos"], batch_id=batch_id + 99), 409)  # not the latest
        self.assertEqual(self.submit(["uno", "dos"]), 200)
        self.assertEqual(self.submit(["uno", "dos"], rows=[0, 1]), 409)             # already sent

    def test_ask_times_out(self):
        r = self.run_nb("ask", "--wait", "--timeout", "1", "the train")
        self.assertEqual(r.returncode, 2)
        self.assertIn("still open", r.stdout)
        self.assertEqual(self.latest()["status"], "open")

    def test_a_new_batch_withdraws_the_waiting_one(self):
        proc = self.start_ask("the train")
        first = self.latest()["id"]
        self.start_ask("the soup")
        self.assertIn("withdrawn", self.finish(proc, 3))
        batches = [i for i in self.state()["items"] if i["kind"] == "batch"]
        self.assertEqual(next(b for b in batches if b["id"] == first)["status"], "cancelled")

    def test_cancel(self):
        proc = self.start_ask("the train")
        self.assertIn("Withdrew", self.ok("cancel"))
        self.finish(proc, 3)
        self.assertEqual(self.latest()["status"], "cancelled")
        self.assertIn("no batch", self.fails("cancel"))

    def test_wait(self):
        self.start_ask("the train")
        self.assertIn("still waiting", self.fails("wait", "--timeout", "0", code=4))
        self.submit(["el tren"])
        self.assertIn("1. the train → el tren", self.ok("wait", "--timeout", "0"))
        self.ok("feedback", "ok")
        self.assertIn("nothing to wait for", self.ok("wait", "--timeout", "0"))

    def test_bad_arguments(self):
        self.fails("ask", "  ")
        self.fails("ask", *["x"] * 31)
        self.fails("ask", "--timeout", "-1", "x")
        self.fails("feedback", "")
        self.fails("feedback", " | reason")
        self.fails("note", " ")


class TestRewrites(NotebookCase):
    def answered(self, *prompts_and_answers):
        prompts, answers = prompts_and_answers[::2], prompts_and_answers[1::2]
        self.start_ask("--title", "Into Spanish", *prompts)
        self.submit(list(answers))
        return self.latest()["id"]

    def test_wrong_answers_get_rewrite_fields(self):
        self.answered("the train", "el tren", "I took", "tome", "last night", "")
        out = self.ok("feedback", "ok", "tomé | the stress is on the é", "anoche")
        self.assertIn("Rewrite fields are open for 2, 3", out)
        batch = self.latest()
        self.assertEqual(batch["status"], "open")
        self.assertEqual(batch["rows"][1]["attempts"][0]["mark"],
                         {"ok": False, "correct": "tomé", "note": "the stress is on the é"})
        self.assertEqual([len(r["attempts"]) for r in batch["rows"]], [1, 2, 2])

        waiter = self.background("wait")
        self.assertEqual(self.submit(["tomé", "anoche"]), 200)
        out = self.finish(waiter)
        self.assertIn("REWRITES", out)
        self.assertIn("2. I took → tomé   (try 2 of 3; before: tome; correct: tomé)", out)
        self.assertIn("3. last night → anoche   (try 2 of 3; before: (no answer); correct: anoche)", out)
        self.assertNotIn("1. the train", out)

        out = self.ok("feedback", "ok", "ok")
        self.assertIn("1/3 right first try · 3/3 after rewriting", out)
        self.assertEqual(self.latest()["status"], "done")

    def test_three_tries_then_the_item_closes(self):
        self.answered("I took", "tome")
        self.ok("feedback", "tomé")
        self.submit(["tome"])
        self.ok("feedback", "tomé")
        self.assertEqual(self.latest()["status"], "open")       # one more try
        self.submit(["tomo"])
        out = self.ok("feedback", "tomé | accent on the é")
        self.assertIn("0/1 right first try.", out)
        batch = self.latest()
        self.assertEqual(batch["status"], "done")
        self.assertEqual(len(batch["rows"][0]["attempts"]), 3)

    def test_marks_must_match_the_answers_to_mark(self):
        self.answered("the train", "el tren", "I took", "tome")
        self.assertIn("2 answers to mark, got 1", self.fails("feedback", "ok"))
        self.ok("feedback", "ok", "tomé")
        self.submit(["tomé"])
        self.assertIn("1 answers to mark, got 2", self.fails("feedback", "ok", "ok"))

    def test_feedback_only_when_there_is_something_to_mark(self):
        self.start_ask("the train")
        self.assertIn("hasn't sent", self.fails("feedback", "ok"))
        self.submit(["el tren"])
        self.ok("feedback", "ok: also «tren» alone", "--comment", "Muy bien.")
        batch = self.latest()
        self.assertEqual(batch["rows"][0]["attempts"][0]["mark"], {"ok": True, "correct": "", "note": "also «tren» alone"})
        self.assertEqual(batch["comment"], "Muy bien.")
        self.assertIn("already marked", self.fails("feedback", "ok"))


class TestWatch(NotebookCase):
    def test_ask_returns_at_once(self):
        out = self.ok("ask", "--title", "Into Spanish", "the train")
        self.assertIn("is on the page (1 prompts).", out)
        self.assertNotIn("Waiting", out)
        self.assertEqual(self.latest()["status"], "open")

    def test_watch_prints_each_submission_once(self):
        watcher = self.background("watch")
        self.ok("ask", "--title", "Into Spanish", "the train", "I took")
        batch_id = self.latest()["id"]
        self.submit(["el tren", "tome"])
        self.assertEqual(self.read_event(watcher),
                         f"ANSWERS (batch {batch_id}: Into Spanish)\n1. the train → el tren\n2. I took → tome\n"
                         "Mark all 1, 2 in this order with ./notebook.py feedback.\n")
        self.ok("feedback", "ok", "tomé | accent")
        self.submit(["tomé"])
        out = self.read_event(watcher)
        self.assertIn("REWRITES", out)
        self.assertIn("2. I took → tomé   (try 2 of 3; before: tome; correct: tomé)", out)
        # A second watcher (e.g. after the first one expired) doesn't repeat what was printed.
        self.assertEqual(self.finish(self.background("watch", "--timeout", "1"), 2), "")

    def test_a_killed_watcher_loses_nothing(self):
        watcher = self.background("watch")
        time.sleep(0.5)                            # its request is now waiting on the server
        watcher.kill()
        watcher.communicate()
        self.ok("ask", "the train")
        self.submit(["el tren"])
        out = self.finish(self.background("watch", "--timeout", "1"), 2)
        self.assertIn("1. the train → el tren", out)

    def test_watch_reports_what_was_sent_while_nobody_watched(self):
        self.ok("ask", "the train")
        self.submit(["el tren"])
        out = self.finish(self.background("watch", "--timeout", "1"), 2)
        self.assertIn("1. the train → el tren", out)

    def test_wait_counts_as_printed(self):
        self.ok("ask", "the train")
        self.submit(["el tren"])
        self.assertIn("el tren", self.ok("wait", "--timeout", "0"))
        self.assertEqual(self.finish(self.background("watch", "--timeout", "1"), 2), "")
        self.assertIn("el tren", self.ok("wait", "--timeout", "0"))    # wait always shows the answers

    def test_feedback_can_wait_for_the_rewrites(self):
        self.ok("ask", "I took")
        self.submit(["tome"])
        proc = self.background("feedback", "--wait", "tomé")
        for _ in range(100):
            if self.latest()["status"] == "open":
                break
            time.sleep(0.05)
        self.submit(["tomé"])
        out = self.finish(proc)
        self.assertIn("Rewrite fields are open for 1.", out)
        self.assertIn("REWRITES", out)


class TestSession(NotebookCase):
    def test_notes_titles_score_and_file(self):
        self.ok("title", "Lección 8 · El pretérito")
        self.ok("note", "--title", "New words", "-", stdin="| español | English |\n|---|---|\n| anoche | last night |\n")
        self.start_ask("--title", "Into Spanish", "I took", "the dinner")
        self.submit(["tome", "la cena"])
        self.ok("feedback", "tomé | stress on the é", "ok")
        self.submit(["tomé"])
        self.ok("feedback", "ok", "--comment", "Watch the accents.")
        st = self.state()
        self.assertEqual(st["title"], "Lección 8 · El pretérito")
        self.assertEqual(st["score"], [1, 2, 2])
        out = self.ok("end")
        self.assertIn("1/2 right first try (50%) · 2/2 after rewriting", out)
        self.assertEqual(self.state()["items"][-1]["kind"], "summary")
        self.assertIn("Session score", self.ok("status").replace("Score so far", "Session score"))

        [session] = self.saved()["sessions"]
        self.assertEqual(session["number"], 1)
        self.assertEqual([i["kind"] for i in session["items"]], ["title", "note", "batch", "summary"])
        title, note, batch, summary = session["items"]
        self.assertEqual(title["text"], "Lección 8 · El pretérito")
        self.assertEqual(note["title"], "New words")
        self.assertIn("| anoche | last night |", note["text"])
        self.assertEqual((batch["title"], batch["status"], batch["score"], batch["comment"]),
                         ("Into Spanish", "done", [1, 2, 2], "Watch the accents."))
        self.assertEqual([[a["text"] for a in r["attempts"]] for r in batch["rows"]], [["tome", "tomé"], ["la cena"]])
        self.assertEqual(batch["rows"][0]["attempts"][0]["mark"],
                         {"ok": False, "correct": "tomé", "note": "stress on the é"})
        self.assertEqual(summary["score"], [1, 2, 2])

    def test_the_file_is_the_page_and_nothing_in_it_can_run(self):
        evil = "</script><script>alert(1)</script> & <img src=x onerror=alert(1)> <!--"
        self.ok("note", "--title", evil, evil)
        text = self.notebook_path().read_text()
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertNotIn("<img", text)
        self.assertNotIn("alert(1)</script>", text)
        self.assertEqual(text.count("</script>"), 2)       # the data and the page's own script
        note = self.saved()["sessions"][0]["items"][-1]
        self.assertEqual((note["title"], note["text"]), (evil, evil))
        # Only the page's own script may run: the CSP pins its hash.
        script = text.rsplit("<script>", 1)[1].split("</script>", 1)[0]
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn(f"script-src 'sha256-{digest}'", text)
        self.assertIn("default-src 'none'", text)
        self.assertIn("img-src data:\">", text)           # the favicon, and no other images

    def test_title_changes_add_a_section(self):
        self.ok("title", "Lección 9")
        self.ok("title", "Lección 9")              # unchanged: no new section
        titles = [i["text"] for i in self.state()["items"] if i["kind"] == "title"]
        self.assertEqual(titles[-1], "Lección 9")
        self.assertEqual(titles.count("Lección 9"), 1)


class TestStartStop(NotebookCase):
    serve = False

    def setUp(self):
        # Each test gets its own notebook folder: these tests count sessions in the day's file.
        folder = Path(tempfile.mkdtemp(dir=self.tmp))
        type(self).env = {**self.env, "NOTEBOOK_DIR": str(folder)}

    def test_commands_report_a_stopped_server(self):
        self.assertIn("Not running", self.fails("status"))
        for args in (["ask", "x"], ["wait"], ["feedback", "ok"], ["note", "x"], ["end"], ["cancel"]):
            self.assertIn("isn't running", self.fails(*args))
        r = self.run_nb("watch")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("NOTEBOOK DOWN"), r.stdout)    # on stdout: it's the event
        self.assertIn("Not running", self.ok("stop"))

    def test_start_reuses_the_session_until_it_ends(self):
        self.addCleanup(self.run_nb, "stop")
        out = self.ok("start", "--title", "Lección 3")
        token = Path(self.env["NOTEBOOK_TOKEN_FILE"]).read_text().strip()
        self.assertIn(f"(started): http://127.0.0.1:{self.port}/?t={token}", out)
        self.assertEqual(os.stat(self.env["NOTEBOOK_TOKEN_FILE"]).st_mode & 0o777, 0o600)
        self.token = token
        self.assertIn("same session", self.ok("start"))
        self.ok("note", "Hola")
        self.assertEqual(self.state()["session"], 1)
        self.ok("end")
        self.assertIn("new session", self.ok("start", "--title", "Lección 4"))
        st = self.state()
        self.assertEqual((st["session"], st["title"], len(st["items"])), (2, "Lección 4", 1))
        self.ok("note", "Adiós")
        first, second = self.saved()["sessions"]
        self.assertEqual((first["number"], self.saved_texts(first)), (1, ["Lección 3", "Hola"]))
        self.assertEqual((second["number"], self.saved_texts(second)), (2, ["Lección 4", "Adiós"]))
        self.assertIn("Stopped", self.ok("stop"))
        self.fails("status")

    def test_watch_exits_quietly_when_stopped_and_reports_a_lost_server(self):
        self.start_server()
        self.addCleanup(self.stop_server)
        watcher = self.background("watch")
        time.sleep(0.5)
        self.ok("stop")
        self.assertEqual(self.finish(watcher, 0), "")
        self.server.wait(10)
        self.server = None

        self.start_server()
        watcher = self.background("watch")
        time.sleep(0.5)
        self.stop_server()                         # killed, not stopped
        self.assertIn("NOTEBOOK DOWN", self.finish(watcher, 1))

    def test_a_new_day_starts_a_new_session(self):
        self.addCleanup(self.run_nb, "stop")
        self.ok("start")
        self.token = Path(self.env["NOTEBOOK_TOKEN_FILE"]).read_text().strip()
        self.assertIn("new session", self.ok("start", env={**self.env, "NOTEBOOK_TODAY": "2026-11-01"}))
        self.assertEqual(self.state()["day"], "2026-11-01")

    def test_a_restarted_server_appends_a_session(self):
        self.start_server()
        self.addCleanup(self.stop_server)
        self.ok("note", "Primera")
        self.stop_server()
        self.start_server()
        self.ok("note", "Segunda")
        self.assertEqual([(x["number"], self.saved_texts(x)) for x in self.saved()["sessions"]],
                         [(1, ["Primera"]), (2, ["Segunda"])])
        self.assertEqual(self.state()["session"], 2)

    def test_an_unreadable_file_is_moved_aside(self):
        folder = Path(self.env["NOTEBOOK_DIR"])
        self.notebook_path().write_text("<p>not a notebook</p>")
        self.start_server()
        self.addCleanup(self.stop_server)
        self.ok("note", "Hola")
        [aside] = folder.glob(f"{TODAY}-unreadable-*.html")
        self.assertEqual(aside.read_text(), "<p>not a notebook</p>")
        self.assertEqual([x["number"] for x in self.saved()["sessions"]], [1])


if __name__ == "__main__":
    unittest.main()
