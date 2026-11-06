"""Shared test helpers: a throwaway database per test, seeded with a fixed fixture.

Tests run vocab.py as a subprocess (the way the tutor uses it) with VOCAB_DB pointing at a
temporary file and VOCAB_TODAY fixed, so they never depend on, or touch, the real vocab.db.
"""
import hashlib
import os
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "vocab.py"
REAL_DB = REPO / "learner" / "vocab.db"
TODAY = "2026-10-31"

# (id, spanish, english, type, lesson, added, box, next_review, notes) — box 6 = mastered.
# Due on TODAY, in expected `due` order: ids 1, 2, 3, 4, 11, 12, 6, 10, 5.
FIXTURE = [
    (1, "el tren", "the train", "noun m.", "4", "2026-10-07", 1, "2026-10-08", ""),
    (2, "la sopa", "the soup", "noun f.", "4", "2026-10-07", 1, "2026-10-08", ""),
    (3, "el problema", "the problem", "noun m.", "5", "2026-10-23", 2, "2026-10-08", ""),
    (4, "la ciudad", "the city", "noun f.", "4", "2026-10-07", 3, "2026-10-20", "spelling: ciu-DAD (not cuidad)"),
    (5, "la estación", "the station", "noun f.", "4", "2026-10-07", 4, "2026-10-31", ""),
    (6, "el avión", "the airplane", "noun m.", "4", "2026-10-07", 5, "2026-10-30", "accent on -ó"),
    (7, "el niño", "the boy", "noun m.", "6", "2026-10-25", 1, "2026-11-01", ""),
    (8, "la canción", "the song", "noun f.", "6", "2026-10-25", 2, "2026-11-05", ""),
    (9, "el café", "coffee", "noun m.", "4", "2026-10-07", 6, None, ""),
    (10, "hablé por teléfono", "I talked on the phone", "phrase", "7", "2026-10-31", 1, "2026-10-31",
     'it\'s "quoted"'),
    (11, "-ty → -dad", "cognate rule", "phrase", "4", "2026-10-07", 1, "2026-10-25", "always feminine | stress -DAD"),
    (12, "la carta", "the letter (mail)", "noun f.", "placement", "2026-09-28", 2, "2026-10-28", "≠ la letra"),
]
DUE_ORDER = ["el tren", "la sopa", "el problema", "la ciudad", "-ty → -dad", "la carta",
             "el avión", "hablé por teléfono", "la estación"]


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class VocabTestCase(unittest.TestCase):
    """Each test gets a fresh, seeded temp DB. Each class verifies the real vocab.db is untouched."""

    seed = True

    @classmethod
    def setUpClass(cls):
        cls._real_db_hash = _hash(REAL_DB)

    @classmethod
    def tearDownClass(cls):
        if _hash(REAL_DB) != cls._real_db_hash:
            raise AssertionError(f"{REAL_DB} was modified by {cls.__name__}")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db = self.tmp / "test.db"
        if self.seed:
            self.ok("init")
            with closing(self.connect()) as con, con:
                con.executemany("INSERT INTO vocab VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", FIXTURE)

    # --- running the script ---
    def run_vocab(self, *args, today=TODAY, db=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("VOCAB_")}
        env["VOCAB_DB"] = str(db or self.db)
        if today is not None:
            env["VOCAB_TODAY"] = today
        assert Path(env["VOCAB_DB"]).resolve() != REAL_DB.resolve(), "refusing to test against the real vocab.db"
        return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)

    def ok(self, *args, **kw) -> str:
        """Run and assert success; return stdout."""
        r = self.run_vocab(*args, **kw)
        self.assertEqual(r.returncode, 0, f"vocab.py {args} failed:\n{r.stderr}")
        return r.stdout

    def fails(self, *args, code=1, **kw) -> str:
        """Run and assert failure with the given exit code, nothing on stdout; return stderr."""
        r = self.run_vocab(*args, **kw)
        self.assertEqual(r.returncode, code, f"vocab.py {args}: expected exit {code}, got {r.returncode}\n"
                                             f"stdout: {r.stdout}\nstderr: {r.stderr}")
        self.assertEqual(r.stdout, "", "errors should not print to stdout")
        return r.stderr

    # --- inspecting the database ---
    def connect(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def sql(self, query, params=()):
        """Run one statement (committed) and return its rows."""
        with closing(self.connect()) as con, con:
            return con.execute(query, params).fetchall()

    def row(self, spanish):
        rows = self.sql("SELECT * FROM vocab WHERE spanish = ?", (spanish,))
        return dict(rows[0]) if rows else None

    def state(self, spanish):
        r = self.row(spanish)
        return (r["box"], r["next_review"])

    def count(self):
        return self.sql("SELECT COUNT(*) FROM vocab")[0][0]

    def snapshot(self):
        return [tuple(r) for r in self.sql("SELECT * FROM vocab ORDER BY id")]
