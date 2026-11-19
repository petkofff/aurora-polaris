# Aurora Polaris — development

These are instructions for **developing** Aurora Polaris. Start Claude Code at the root of the
repo and ask it to read this file. They don't apply to tutoring sessions.

Aurora Polaris is a suite of textbook tutors that run in Claude Code. Each tutor follows one
textbook and lives in its own folder (`Madrigal-Spanish-Tutor/`, `Lyons-DSP-Tutor/`). See `README.md`
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

- The code is `vocab.py` and `notebook.py`: Python 3.10+, standard library only. The tutor uses
  them through their CLIs, so keep their output and exit codes stable and readable.
- `notebook.py` serves the notebook page (HTML and JavaScript inside the script, no external files)
  on 127.0.0.1 and checks the token and the `Host` header on every request. It keeps the session in
  memory and rewrites `learner/notebook/YYYY-MM-DD.html` on every change: the same page in read-only
  mode, with the day's sessions embedded as JSON (`<`, `>`, `&` escaped) and a CSP that allows only
  the page's own script, by hash. Earlier sessions of the day are read back from that JSON.
  The tutor keeps `watch` running under the Monitor tool: its stdout is the event stream, so it
  prints only the learner's submissions (and `NOTEBOOK DOWN`), and each one wakes the tutor with
  the answers in the notification. A submission counts as printed only when the client confirms it
  (`/api/printed`), so a killed watcher loses nothing; keep it that way. `ask --wait` /
  `feedback --wait` / `wait` are the fallback for agents without Monitor. The page's Markdown
  renderer builds DOM nodes and never uses `innerHTML`; keep it that way.
- Run the tests from the tutor's folder:
  `cd Madrigal-Spanish-Tutor && python3 -m unittest discover -s tests`.
  They run `vocab.py` as a subprocess against temporary databases (`VOCAB_DB`, `VOCAB_TODAY`)
  and fail if the real `learner/vocab.db` changes. `test_notebook.py` starts its own server on a free
  port, with a temporary token and notebook folder (`NOTEBOOK_PORT`, `NOTEBOOK_TOKEN_FILE`,
  `NOTEBOOK_DIR`, `NOTEBOOK_TODAY`), and fails if the real `.notebook-token` or
  `learner/notebook/` changes. Keep it that way, and add tests with any change to `vocab.py` or
  `notebook.py`. The tests don't cover the
  page's JavaScript; check changes to it in a browser.
- To read the textbook, extract a few pages at a time with
  `pdftotext -layout -f <first> -l <last> "<pdf>" -`, never the whole PDF.

## Lyons-DSP-Tutor

- Section reviews live in the **Box** / **Next review** columns of `learner/progress.md` (format
  in `CLAUDE.md` §4.2), not in a database. If that table turns out to drift, a small
  standard-library script (like `vocab.py`) is the fix.
- `jupyter/wait_answer.py` waits for the learner to submit an answer in the live notebook; the
  tutor runs it in the background. It reads the shared document through `jupyter-nbmodel-client`
  and notices a lost connection through a private field of that client, so check it when
  upgrading the pinned packages.
- Run the tests from the tutor's folder: `.venv/bin/python -m unittest discover -s tests`.
  `test_detection.py` tests the submission logic with plain data (system `python3` works too).
  `test_watcher.py` starts its own JupyterLab in a temporary folder, on a free port, with its own
  token, and is skipped without the venv packages. The tests never touch the learner's JupyterLab,
  `learner/` or `.jupyter-token`. Keep it that way, and add tests with any change to `wait_answer.py`.
- Labs and the tutor's numeric checks need numpy, scipy and matplotlib, usually in the tutor's
  `.venv/` (gitignored). `.claude/settings.json` allows `pdftotext` and running scripts in
  `learner/lab/`.
- The PDF's bookmarks give PDF page numbers for every section
  (`qpdf --json --json-key=outlines …`, field `destpageposfrom1`). `pdftotext` prints harmless
  syntax errors on this PDF; send stderr to `/dev/null`.
