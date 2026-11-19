# Madrigal Spanish Tutor

Part of [Aurora Polaris](../README.md). A Spanish tutor that runs in
[Claude Code](https://claude.com/claude-code). It follows the textbook *Madrigal's Magic Key to
Spanish* (Margarita Madrigal, 1951) lesson by lesson. It remembers the learner between sessions
through the files in `learner/`: profile, progress, error patterns, vocabulary with spaced
repetition, and a log for each session.

`CLAUDE.md` holds the tutor's instructions. Claude Code loads it automatically when started here.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ (standard library only)
- `sqlite3` command-line tool (optional: for readable `git diff` of the vocabulary database)
- `pdftotext` from poppler (`poppler-utils` on Debian/Ubuntu, `poppler` on Arch/macOS Homebrew)
- The textbook PDF, saved in this folder as `Madrigal's Magic Key to Spanish.pdf`.
  It is **not** in the repo (`*.pdf` is gitignored).
- Optional: `qpdf`, to read the PDF's bookmarks when the tutor builds the textbook map.

## Getting started

```sh
cd Madrigal-Spanish-Tutor
claude
```

Then type `hola`.

- **First launch** (no `learner/profile.md` yet): the tutor follows `bootstrap.md`. If there's no
  `learner/textbook-mapping.md`, it first builds one from the PDF. Then it interviews you
  (goals, schedule, explanation language, correction style…), may run a short placement check,
  and creates the learner files in `learner/`.
- **Every session after that**: the tutor loads your files, warms up with due vocabulary and
  your recurring mistakes, teaches the next part of the current lesson, and saves notes at the end.

You can say these at any time: **review**, **quiz me**, **explain X**, **stats**,
**show my vocab**, **end session**.

## Notebook page (`notebook.py`)

Next to the terminal, the tutor keeps a notebook: a local web page that holds what you write and
what you'll want to reread. The conversation stays in the terminal.

- **Batches of questions** (vocabulary review, translation exercises, quizzes): each question has
  its own numbered field. Enter moves to the next one; Enter on the last one sends the batch.
- **Corrections and rewrites:** the tutor marks each answer ✓ or ✗ with the correct form and a
  short reason. A wrong answer gets a field to write it again, with one more try if the rewrite
  is still wrong.
- **Notes:** the new words, a conjugation table, a rule in a line or two.
- **Score:** each batch shows how many you got right on the first try and after rewriting. At the
  end of the session the page shows the session score, and the tutor copies it into the session log.

The page heading shows the current lesson and topic, and the whole session stays on the page.
Everything is also saved to `learner/notebook/YYYY-MM-DD.md`, so you can reread it later.

The tutor starts the server at the start of each session (`./notebook.py start`) and gives you the
link, `http://127.0.0.1:8765/?t=…`. The server listens on 127.0.0.1 only. The token in the link
is kept in `.notebook-token` (gitignored) and stays the same between sessions, so you can bookmark
it. If the page can't start, the tutor carries on in the terminal. To stop using the page, tell
the tutor; it notes that in your profile.

```sh
./notebook.py start --title "Lección 8 · El pretérito"   # start or reuse the server, print the link
./notebook.py note --title "Words" "**anoche**: last night"
./notebook.py watch                                     # print answers and rewrites as they're sent
./notebook.py ask --title "Into Spanish" "the train" "I took"   # post a batch
./notebook.py feedback ok "tomé | stress on the é"      # mark them; wrong ones get a rewrite field
./notebook.py end                                       # session score
./notebook.py stop
./notebook.py --help                                    # all commands and exit codes
```

While you answer, the terminal stays free: the tutor runs `./notebook.py watch` under Claude Code's
Monitor tool, which wakes it with your answers when you send them. Without Monitor, it waits with
`ask --wait` in the background instead (one more step per batch, so a few more tokens).

To use another port, set `NOTEBOOK_PORT` (e.g. in `.claude/settings.local.json` under `env`).

## Files

| File | What it is | Who writes it |
|---|---|---|
| `CLAUDE.md` | Tutor instructions: session workflow, teaching rules, file formats | you |
| `bootstrap.md` | First-launch interview and setup | you |
| `learner/profile.md` | Learner profile: goals, schedule, preferences, level | tutor |
| `learner/progress.md` | Status of every lesson, checkpoint scores | tutor |
| `learner/errors.md` | Recurring error patterns and an error log | tutor |
| `learner/vocab.db` | Vocabulary with Leitner boxes (SQLite) | tutor, via `vocab.py` |
| `learner/log/YYYY-MM-DD.md` | What happened in each session and where to resume | tutor |
| `learner/textbook-mapping.md` | Lesson → PDF page ranges and topics | tutor, at first launch |
| `vocab.py` | Command-line tool for the vocabulary database | you |
| `learner/notebook/YYYY-MM-DD.md` | Everything that was on the notebook page, per session | `notebook.py` |
| `notebook.py` | The notebook page: a local web page beside the terminal | you |
| `tests/` | Tests for `vocab.py` and `notebook.py` | you |

The learner files are personal data. They live in `learner/`, which this repo ignores, so they
never end up in a commit of Aurora Polaris. To start over with a new learner, delete
`learner/`; the next launch runs the bootstrap again.

### Backing up `learner/`

To keep the learner files safe, make `learner/` its own **private** git repo and commit after
sessions:

```sh
cd learner
git init -b main
printf '*.db diff=sqlite3\n' > .gitattributes
git config diff.sqlite3.textconv 'sqlite3 -readonly "$1" .dump #'   # show vocab.db changes as SQL
git config diff.sqlite3.binary true
git add -A && git commit -m "Learner data"
git remote add origin <private-url> && git push -u origin main
```

On another machine, clone Aurora Polaris, then clone the private repo into
`Madrigal-Spanish-Tutor/learner/`, and run the two `git config` lines again (they're per clone).

## Vocabulary (`vocab.py`)

Vocabulary is stored in SQLite, so the tutor never loads the whole list. It asks the script for
what it needs:

```sh
./vocab.py due 10                              # words due for review, most overdue first
./vocab.py review "el tren" right "la sopa" wrong
./vocab.py add "el mono" "the monkey" "noun m." 1 --notes "≠ la mona"
./vocab.py find avion                          # ignores accents and case
./vocab.py stats
./vocab.py export --all                        # Markdown table of everything
./vocab.py --help                              # all commands
```

Spaced repetition uses Leitner boxes with intervals of 1, 3, 7, 14 and 30 days. A right answer
moves a word up one box; right in box 5 means mastered. A wrong answer sends it back to box 1.
The intervals are stored in the `intervals` table of `learner/vocab.db`, so they can be changed there.

`.claude/settings.json` lets the tutor run `./vocab.py` and `./notebook.py` without a permission prompt.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The tests run `vocab.py` against temporary databases with a fixed date. They never touch the
real `learner/vocab.db`. The `notebook.py` tests start their own server on a free port, with a
temporary token and notebook folder, so they don't touch a running notebook, `.notebook-token` or
`learner/notebook/`.

## License

GPL-2.0-only, like the rest of Aurora Polaris. See [`LICENSE`](../LICENSE). The textbook is not
covered by this license and is not included.
