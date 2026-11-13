# Lyons DSP Tutor

Part of [Aurora Polaris](../README.md). A digital signal processing tutor that runs in
[Claude Code](https://claude.com/claude-code). It follows the textbook *Understanding Digital
Signal Processing*, 3rd edition (Richard G. Lyons, 2011), section by section. It remembers the
learner between sessions through the files in `learner/`: profile, progress with a review
schedule for every finished section, misconception patterns, labs, and a log for each session.

`CLAUDE.md` holds the tutor's instructions. Claude Code loads it automatically when started here.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ with numpy, scipy and matplotlib, for labs and for checking answers. On first
  launch the tutor offers to create a virtual environment in `.venv/` with them.
- `pdftotext` from poppler (`poppler-utils` on Debian/Ubuntu, `poppler` on Arch/macOS Homebrew)
- The textbook PDF, saved in this folder as `Understanding-Digital-Signal-Processing.pdf`.
  It is **not** in the repo (`*.pdf` is gitignored).
- Optional: `qpdf`, to read the PDF's bookmarks when the tutor builds the textbook map.

## Getting started

```sh
cd Lyons-DSP-Tutor
claude
```

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

Type math however is easiest for you: LaTeX (`\sum_{n=0}^{N-1} x(n)`), plain ASCII
(`e^(-j*2*pi*m/N)`) or code. The tutor answers in plain Unicode (`Σ`, `π`, `ω`), which the
terminal can show without LaTeX rendering.

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
| `learner/profile.md` | Learner profile: background, goals, track, preferences, lab setup | tutor |
| `learner/progress.md` | Plan and status of every section, review schedule, checkpoint scores, labs | tutor |
| `learner/errors.md` | Recurring misconception patterns and an error log | tutor |
| `learner/lab/` | Your lab code; `tutor/` holds the tutor's own checks, `plots/` the saved figures | you and tutor |
| `learner/log/YYYY-MM-DD.md` | What happened in each session and where to resume | tutor |
| `learner/textbook-mapping.md` | Section → PDF page ranges and topics | tutor, at first launch |
| `.venv/` | Python virtual environment for labs (optional, gitignored) | tutor, at first launch |

The learner files are personal data. They live in `learner/`, which this repo ignores, so they
never end up in a commit of Aurora Polaris. To start over with a new learner, delete
`learner/`; the next launch runs the bootstrap again.

`.claude/settings.json` lets the tutor run `pdftotext` and the scripts in `learner/lab/`
without a permission prompt.

### Backing up `learner/`

To keep the learner files safe, make `learner/` its own **private** git repo and commit after
sessions:

```sh
cd learner
git init -b main
printf 'lab/plots/\n__pycache__/\n' > .gitignore   # plots can be regenerated
git add -A && git commit -m "Learner data"
git remote add origin <private-url> && git push -u origin main
```

On another machine, clone Aurora Polaris, then clone the private repo into
`Lyons-DSP-Tutor/learner/`.

## License

GPL-2.0-only, like the rest of Aurora Polaris. See [`LICENSE`](../LICENSE). The textbook is not
covered by this license and is not included.
