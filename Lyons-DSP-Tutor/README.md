# Lyons DSP Tutor

Part of [Aurora Polaris](../README.md). A digital signal processing tutor that runs in
[Claude Code](https://claude.com/claude-code). It follows the textbook *Understanding Digital
Signal Processing*, 3rd edition (Richard G. Lyons, 2011), section by section. It remembers the
learner between sessions through the files in `learner/`: profile, progress with a review
schedule for every finished section, misconception patterns, labs, and a log for each session.

The conversation happens in Claude Code. Optionally, the tutor also works in a live
**JupyterLab notebook** next to it: explanations with rendered LaTeX, plots inline, and cells
where you answer and write code. Without JupyterLab, everything happens in the terminal.

`CLAUDE.md` holds the tutor's instructions. Claude Code loads it automatically when started here.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3, for labs, for the tutor's numeric checks and for JupyterLab. The pinned packages in
  `requirements-lab.txt` (numpy, scipy, matplotlib, JupyterLab, the Jupyter MCP server) were
  tested with Python 3.14. On first launch the tutor offers to install them in `.venv/`, or do it
  yourself:
  ```sh
  python3 -m venv .venv && .venv/bin/pip install -r requirements-lab.txt
  ```
- `pdftotext` from poppler (`poppler-utils` on Debian/Ubuntu, `poppler` on Arch/macOS Homebrew),
  for the book's text. For figures and equations, which don't survive text extraction, the tutor
  views the page as an image. It names the figure and PDF page so you can look too, and in the
  notebook it redraws key figures with code.
- The textbook PDF, saved in this folder as `Understanding-Digital-Signal-Processing.pdf`.
  It is **not** in the repo (`*.pdf` is gitignored).
- Optional: `qpdf`, to read the PDF's bookmarks when the tutor builds the textbook map.

## Getting started

**Terminal only:**

```sh
cd Lyons-DSP-Tutor
claude
```

**With the notebook:** use two terminals, both in `Lyons-DSP-Tutor/`.

```sh
jupyter/start-lab.sh     # terminal 1: JupyterLab opens in your browser
claude                   # terminal 2
```

On the first start, Claude Code asks you to approve the project's MCP server `jupyter` (from
`.mcp.json`). `/mcp` shows whether it's connected. Start JupyterLab before Claude Code; if you
start it later, reconnect the server with `/mcp`.

Then type `hi`.

- **First launch** (no `learner/profile.md` yet): the tutor follows `bootstrap.md`. It checks
  the tools, builds `learner/textbook-mapping.md` from the PDF if it's missing, then interviews
  you (math and programming background, goals, track, rigor, correction style…). It runs a short
  prerequisite check, places you in the book, proposes a plan of core and elective sections for
  your track, and creates the learner files in `learner/`.
- **Every session after that**: the tutor loads your files, warms up with reviews of finished
  sections that are due and your recurring misconceptions, teaches the next part of the book,
  and saves notes at the end.

You can say these at any time: **review**, **quiz me**, **explain X**, **lab**, **stats**,
**end session**.

## Working in the notebook

The tutor keeps one notebook per chapter (`learner/lab/ch03.ipynb`, …). Open it in JupyterLab;
the tutor's cells appear there as it adds them.

- **Answering:** write your answer in a cell, then press **Shift+Enter**. That submits it: the
  tutor wakes up, reads the answer and replies. Running a code cell submits it too. You don't
  need to type anything in the terminal, but you still can, and that works as well.
- **Your cells are yours:** the tutor only adds cells at the end. It never edits, moves or
  deletes your cells, and it asks before restarting the kernel (a restart wipes your variables).
  A new notebook starts with a placeholder cell; delete it yourself.
- **Shared kernel:** the tutor's code runs in the same kernel as yours. Its variables start with
  `_`, so they don't overwrite yours.
- If you don't answer within 20 minutes, the tutor stops waiting and says so in the terminal.
  If JupyterLab stops, the tutor continues in the terminal.

## Typing math

Type math however is easiest for you: LaTeX (`\sum_{n=0}^{N-1} x(n)`), plain ASCII
(`e^(-j*2*pi*m/N)`) or code. In the notebook, LaTeX in a markdown cell renders when you press
Shift+Enter. In the terminal, the tutor answers in plain Unicode (`Σ`, `π`, `ω`), which shows
without LaTeX rendering.

## How reviews work

Every finished section comes back for one new question on an expanding schedule: 3, 7, 21 and
60 days. A right answer moves it to the next interval; right at 60 days retires it. A wrong
answer brings it back the next day. The schedule is kept in the **Box** and **Next review**
columns of `learner/progress.md`.

Chapter problems are checkpoints. The book has no answer key, so the tutor solves each problem
with code before grading your answer.

## Files

| File | What it is | Who writes it |
|---|---|---|
| `CLAUDE.md` | Tutor instructions: session workflow, teaching rules, file formats | you |
| `bootstrap.md` | First-launch interview and setup | you |
| `requirements-lab.txt` | Pinned Python packages for labs and the notebook | you |
| `jupyter/start-lab.sh` | Starts JupyterLab on 127.0.0.1:8888, with the token in `.jupyter-token` | you |
| `jupyter/mcp.sh`, `.mcp.json` | The Jupyter MCP server the tutor uses to work in the notebook | you |
| `jupyter/wait_answer.py` | Waits in the background until you submit an answer in the notebook | you |
| `tests/` | Tests for `wait_answer.py` | you |
| `learner/profile.md` | Learner profile: background, goals, track, preferences, lab setup | tutor |
| `learner/progress.md` | Plan and status of every section, review schedule, checkpoint scores, labs | tutor |
| `learner/errors.md` | Recurring misconception patterns and an error log | tutor |
| `learner/lab/` | Notebooks and lab code; `tutor/` holds the tutor's own checks, `plots/` saved figures | you and tutor |
| `learner/log/YYYY-MM-DD.md` | What happened in each session and where to resume | tutor |
| `learner/textbook-mapping.md` | Section → PDF page ranges and topics | tutor, at first launch |
| `.venv/` | Python virtual environment (gitignored) | tutor or you, at setup |
| `.jupyter-token` | JupyterLab's access token, created by `start-lab.sh` (gitignored) | `start-lab.sh` |

`.claude/settings.json` lets the tutor run `pdftotext`, the scripts in `learner/lab/` and
`jupyter/wait_answer.py`, and read, add and run notebook cells, without a permission prompt.
Editing, moving, deleting or clearing cells is denied.

## Your data stays private

The learner files are personal data. They live in `learner/`, which this repo ignores, so they
never end up in a commit of Aurora Polaris. JupyterLab's local state (`.jupyter/` and
`.jupyter_ystore.db`, which holds notebook contents) and `.jupyter-token` are ignored too.
JupyterLab listens on 127.0.0.1 only, so it isn't reachable from other machines.

To start over with a new learner, delete `learner/`; the next launch runs the bootstrap again.

### Backing up `learner/`

To keep the learner files safe, make `learner/` its own **private** git repo and commit after
sessions:

```sh
cd learner
git init -b main
printf 'lab/plots/\n__pycache__/\n.ipynb_checkpoints/\n' > .gitignore   # plots can be regenerated
git add -A && git commit -m "Learner data"
git remote add origin <private-url> && git push -u origin main
```

On another machine, clone Aurora Polaris, then clone the private repo into
`Lyons-DSP-Tutor/learner/`.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

`test_detection.py` checks how `wait_answer.py` recognizes a submitted answer. `test_watcher.py`
runs it against a throwaway JupyterLab on a free port, with its own token, and is skipped when the
venv packages aren't installed. The tests never touch your JupyterLab, `learner/` or
`.jupyter-token`.

## License

GPL-2.0-only, like the rest of Aurora Polaris. See [`LICENSE`](../LICENSE). The textbook is not
covered by this license and is not included.
