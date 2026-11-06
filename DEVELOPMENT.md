# Aurora Polaris — development

These are instructions for **developing** Aurora Polaris. Start Claude Code at the root of the
repo and ask it to read this file. They don't apply to tutoring sessions.

Aurora Polaris is a suite of language tutors that run in Claude Code. Each tutor follows one
textbook and lives in its own folder (`Madrigal-Spanish-Tutor/` is the first). See `README.md`
for the layout and the rules for adding a tutor.

## Privacy: this repo is public

- Each tutor keeps its learner's data in `<tutor>/learner/`. That folder is ignored here and is
  usually the learner's own **private** git repo. Never stage, commit or copy anything from it
  into this repo.
- Don't read learner files unless the task needs them; ask first. Never edit them during
  development.
- Textbook PDFs are ignored too and must never be committed. Don't quote large parts of a book
  in tracked files.
- Keep every tracked file generic: no names, personal details, or examples taken from real
  sessions. When you need example vocabulary or errors, use ones from the textbook or make them up.
- Before every commit, read `git status` and check that only the intended files are staged.
- Commit only when asked, and push only when asked.

## Working on a tutor

- A tutor's `CLAUDE.md` and `bootstrap.md` are instructions for the tutor, not for you. Edit them
  as prompts: short, imperative, unambiguous. Keep paths relative to the tutor's folder.
- When you change a learner file format, a path or a command, update every place that mentions it:
  the tutor's `CLAUDE.md`, `bootstrap.md` (its templates too), its `README.md`, its tools, and
  its tests.
- Never add a `CLAUDE.md` (or `.claude/CLAUDE.md`, `.claude/rules/`) at the root of the repo.
  Claude Code loads those in every tutor's session too.
- To try out a change, start a **separate** Claude Code session inside the tutor's folder.
  Without a real learner, use a fresh clone of the repo, so no real `learner/` is touched.

## Madrigal-Spanish-Tutor

- `vocab.py` is the only code: Python 3.10+, standard library only. The tutor uses it through its
  CLI, so keep its output stable and readable.
- Run the tests from the tutor's folder:
  `cd Madrigal-Spanish-Tutor && python3 -m unittest discover -s tests`.
  They run `vocab.py` as a subprocess against temporary databases (`VOCAB_DB`, `VOCAB_TODAY`)
  and fail if the real `learner/vocab.db` changes. Keep it that way, and add tests with any
  change to `vocab.py`.
- To read the textbook, extract a few pages at a time with
  `pdftotext -layout -f <first> -l <last> "<pdf>" -`, never the whole PDF.
