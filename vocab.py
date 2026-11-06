#!/usr/bin/env python3
"""Vocabulary store for the Spanish tutor (SQLite, Leitner spaced repetition).

Commands:
  due [N]                          words due for review, most overdue first (default 10)
  review WORD right|wrong [...]    record review results; several WORD RESULT pairs allowed
  add WORD ENGLISH TYPE LESSON [--notes N] [--box B]
                                   add a new word (box 1, due tomorrow, unless --box)
  find TERM                        search Spanish/English/notes (ignores accents and case)
  edit WORD [--spanish S] [--english E] [--type T] [--lesson L] [--notes N]
                                   fix a word's details (not its review state)
  delete WORD                      remove a word
  stats                            counts per box, due today, mastered
  export [--all]                   print a Markdown table (default: not mastered; --all: everything)
  init                             create an empty database (first launch)

Leitner boxes: 1 → 1 day · 2 → 3 days · 3 → 7 days · 4 → 14 days · 5 → 30 days.
Right: up one box, next review = today + that box's interval. Right in box 5 → mastered.
Wrong: back to box 1, next review = tomorrow.

Env: VOCAB_DB (database path, default learner/vocab.db next to this script),
     VOCAB_TODAY (YYYY-MM-DD, override today's date — for testing).
"""
import argparse
import os
import sqlite3
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("VOCAB_DB", Path(__file__).resolve().parent / "learner" / "vocab.db"))
MASTERED = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS vocab (
    id          INTEGER PRIMARY KEY,
    spanish     TEXT NOT NULL UNIQUE,
    english     TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT '',
    lesson      TEXT NOT NULL DEFAULT '',
    added       TEXT NOT NULL,                       -- YYYY-MM-DD
    box         INTEGER NOT NULL DEFAULT 1 CHECK (box BETWEEN 1 AND 6),  -- 6 = mastered
    next_review TEXT,                                -- YYYY-MM-DD; NULL when mastered
    notes       TEXT NOT NULL DEFAULT '',
    CHECK ((box = 6) = (next_review IS NULL))
);
CREATE INDEX IF NOT EXISTS vocab_next_review ON vocab(next_review);
CREATE TABLE IF NOT EXISTS intervals (
    box  INTEGER PRIMARY KEY CHECK (box BETWEEN 1 AND 5),
    days INTEGER NOT NULL CHECK (days > 0)
);
INSERT OR IGNORE INTO intervals (box, days) VALUES (1, 1), (2, 3), (3, 7), (4, 14), (5, 30);
"""


def today() -> date:
    override = os.environ.get("VOCAB_TODAY")
    if not override:
        return date.today()
    try:
        return date.fromisoformat(override)
    except ValueError:
        sys.exit(f"error: VOCAB_TODAY must be YYYY-MM-DD, got '{override}'")


def contains(term: str) -> str:
    """LIKE pattern matching `term` anywhere, accent/case-folded, with % and _ taken literally."""
    escaped = fold(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def fold(s: str) -> str:
    """Lowercase and strip accents, for forgiving search (á→a, ñ→n, ü→u)."""
    if s is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def connect(create: bool = False) -> sqlite3.Connection:
    if not create and not DB_PATH.exists():
        sys.exit(f"error: {DB_PATH} not found (run `vocab.py init` first)")
    if create:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.create_function("fold", 1, fold, deterministic=True)
    con.executescript(SCHEMA)
    return con


def lookup(con, word: str):
    """Exact match on Spanish; otherwise a unique accent/case-insensitive match. Exits on failure."""
    row = con.execute("SELECT * FROM vocab WHERE spanish = ?", (word,)).fetchone()
    if row:
        return row
    rows = con.execute("SELECT * FROM vocab WHERE fold(spanish) = fold(?)", (word,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        sys.exit(f"error: '{word}' is ambiguous: {', '.join(r['spanish'] for r in rows)} — use the exact spelling")
    similar = con.execute(
        "SELECT spanish FROM vocab WHERE fold(spanish) LIKE ? ESCAPE '\\' LIMIT 8", (contains(word),)
    ).fetchall()
    hint = f" — did you mean: {', '.join(r['spanish'] for r in similar)}" if similar else ""
    sys.exit(f"error: no word '{word}'{hint}")


def fmt(r) -> str:
    state = "mastered" if r["box"] == MASTERED else f"box {r['box']}, due {r['next_review']}"
    notes = f" — {r['notes']}" if r["notes"] else ""
    return f"{r['spanish']} | {r['english']} | {r['type']} | L{r['lesson']} | {state}{notes}"


def cmd_due(con, a):
    t = today().isoformat()
    total = con.execute("SELECT COUNT(*) FROM vocab WHERE next_review <= ?", (t,)).fetchone()[0]
    rows = con.execute(
        "SELECT * FROM vocab WHERE next_review <= ? ORDER BY next_review, box, id LIMIT ?", (t, a.n)
    ).fetchall()
    print(f"Due on {t}: {total} word(s); showing {len(rows)} (most overdue first)")
    for r in rows:
        print(fmt(r))


def cmd_review(con, a):
    if len(a.pairs) % 2:
        sys.exit("error: give WORD RESULT pairs, e.g. review 'el tren' right 'la sopa' wrong")
    pairs = list(zip(a.pairs[::2], a.pairs[1::2]))
    for _, res in pairs:
        if res not in ("right", "wrong"):
            sys.exit(f"error: result must be 'right' or 'wrong', got '{res}'")
    rows = [lookup(con, w) for w, _ in pairs]  # validate everything before writing anything
    intervals = dict(con.execute("SELECT box, days FROM intervals").fetchall())
    t = today()
    with con:
        for r, (_, res) in zip(rows, pairs):
            old = r["box"]
            if res == "wrong":
                box, nxt = 1, (t + timedelta(days=1)).isoformat()
            elif old >= 5:
                box, nxt = MASTERED, None
            else:
                box = old + 1
                nxt = (t + timedelta(days=intervals[box])).isoformat()
            con.execute("UPDATE vocab SET box = ?, next_review = ? WHERE id = ?", (box, nxt, r["id"]))
            new = "mastered" if box == MASTERED else f"box {box}, next {nxt}"
            print(f"{r['spanish']}: {res} — box {old} → {new}")


def cmd_add(con, a):
    if a.box == MASTERED:
        nxt = None
    else:
        days = 1 if a.box == 1 else con.execute("SELECT days FROM intervals WHERE box = ?", (a.box,)).fetchone()[0]
        nxt = (today() + timedelta(days=days)).isoformat()
    dup = con.execute("SELECT * FROM vocab WHERE fold(spanish) = fold(?)", (a.spanish,)).fetchone()
    if dup:
        sys.exit(f"error: already exists: {fmt(dup)}")
    with con:
        con.execute(
            "INSERT INTO vocab (spanish, english, type, lesson, added, box, next_review, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (a.spanish, a.english, a.type, a.lesson, today().isoformat(), a.box, nxt, a.notes),
        )
    print(f"added: {fmt(lookup(con, a.spanish))}")


def cmd_find(con, a):
    rows = con.execute(
        "SELECT * FROM vocab WHERE fold(spanish) LIKE ?1 ESCAPE '\\'"
        " OR fold(english) LIKE ?1 ESCAPE '\\' OR fold(notes) LIKE ?1 ESCAPE '\\'"
        " ORDER BY id",
        (contains(a.term),),
    ).fetchall()
    print(f"{len(rows)} match(es) for '{a.term}'")
    for r in rows:
        print(fmt(r))


def cmd_edit(con, a):
    r = lookup(con, a.word)
    changes = {k: v for k, v in (("spanish", a.spanish), ("english", a.english), ("type", a.type),
                                 ("lesson", a.lesson), ("notes", a.notes)) if v is not None}
    if not changes:
        sys.exit("error: nothing to change (use --spanish/--english/--type/--lesson/--notes)")
    if "spanish" in changes:
        dup = con.execute("SELECT 1 FROM vocab WHERE fold(spanish) = fold(?) AND id != ?",
                          (changes["spanish"], r["id"])).fetchone()
        if dup:
            sys.exit(f"error: another word is already '{changes['spanish']}'")
    with con:
        con.execute(f"UPDATE vocab SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                    (*changes.values(), r["id"]))
    print(f"updated: {fmt(con.execute('SELECT * FROM vocab WHERE id = ?', (r['id'],)).fetchone())}")


def cmd_delete(con, a):
    r = lookup(con, a.word)
    with con:
        con.execute("DELETE FROM vocab WHERE id = ?", (r["id"],))
    print(f"deleted: {fmt(r)}")


def cmd_stats(con, a):
    t = today().isoformat()
    total = con.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
    due = con.execute("SELECT COUNT(*) FROM vocab WHERE next_review <= ?", (t,)).fetchone()[0]
    boxes = dict(con.execute("SELECT box, COUNT(*) FROM vocab GROUP BY box").fetchall())
    print(f"Total words: {total} · due today ({t}): {due} · mastered: {boxes.get(MASTERED, 0)}")
    print("By box: " + " · ".join(f"{b}: {boxes.get(b, 0)}" for b in range(1, 6)))
    print("By lesson: " + " · ".join(
        f"{r[0]}: {r[1]}" for r in con.execute(
            "SELECT lesson, COUNT(*) FROM vocab GROUP BY lesson ORDER BY MIN(id)").fetchall()))


def cmd_export(con, a):
    where = "" if a.all else f"WHERE box != {MASTERED}"
    print("| Spanish | English | Type | Lesson | Added | Box | Next review | Notes |")
    print("|---------|---------|------|--------|-------|-----|-------------|-------|")
    for r in con.execute(f"SELECT * FROM vocab {where} ORDER BY id"):
        box = "M" if r["box"] == MASTERED else r["box"]
        cells = [r["spanish"], r["english"], r["type"], r["lesson"], r["added"], box,
                 r["next_review"] or "—", r["notes"]]
        print("|" + "|".join(f" {c} " if c != "" else " " for c in (str(c).replace("|", "/") for c in cells)) + "|")


def cmd_init(con, a):
    print(f"ready: {DB_PATH}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("due"); s.add_argument("n", nargs="?", type=int, default=10); s.set_defaults(f=cmd_due)
    s = sub.add_parser("review"); s.add_argument("pairs", nargs="+", metavar="WORD RESULT"); s.set_defaults(f=cmd_review)
    s = sub.add_parser("add")
    for x in ("spanish", "english", "type", "lesson"):
        s.add_argument(x)
    s.add_argument("--notes", default="")
    s.add_argument("--box", type=int, default=1, choices=range(1, 7))
    s.set_defaults(f=cmd_add)
    s = sub.add_parser("find"); s.add_argument("term"); s.set_defaults(f=cmd_find)
    s = sub.add_parser("edit"); s.add_argument("word")
    for x in ("spanish", "english", "type", "lesson", "notes"):
        s.add_argument(f"--{x}")
    s.set_defaults(f=cmd_edit)
    s = sub.add_parser("delete"); s.add_argument("word"); s.set_defaults(f=cmd_delete)
    s = sub.add_parser("stats"); s.set_defaults(f=cmd_stats)
    s = sub.add_parser("export"); s.add_argument("--all", action="store_true"); s.set_defaults(f=cmd_export)
    s = sub.add_parser("init"); s.set_defaults(f=cmd_init)
    a = p.parse_args()
    con = connect(create=a.cmd == "init")
    try:
        a.f(con, a)
    finally:
        con.close()


if __name__ == "__main__":
    main()
