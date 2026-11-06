# Claude Spanish Tutor

A Spanish tutor that runs in [Claude Code](https://claude.com/claude-code). It follows the
textbook *Madrigal's Magic Key to Spanish* (Margarita Madrigal, 1951) lesson by lesson. It
remembers the learner between sessions through the files in `learner/`: profile, progress,
error patterns, vocabulary with spaced repetition, and a log for each session.

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
cd claude-spanish-tutor
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
| `tests/` | Tests for `vocab.py` | you |

The learner files are personal data. They live in `learner/`, which this repo ignores, so they
never end up in a commit here. To start over with a new learner, delete `learner/`; the next
launch runs the bootstrap again.

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

On another machine, clone this repo, then clone the private repo into `learner/` inside it, and
run the two `git config` lines again (they're per clone).

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

`.claude/settings.json` lets the tutor run `./vocab.py` without a permission prompt.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The tests run `vocab.py` against temporary databases with a fixed date. They never touch the
real `learner/vocab.db`.

## License

Copyright (C) 2026 petkofff

This program is free software; you can redistribute it and/or modify it under the terms of the
GNU General Public License, version 2 only (`GPL-2.0-only`). See [`LICENSE`](LICENSE).

The textbook is not covered by this license and is not included.
