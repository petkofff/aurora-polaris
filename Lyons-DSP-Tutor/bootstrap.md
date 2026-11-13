# Bootstrap — first launch only

Run this once, when `learner/profile.md` doesn't exist yet. Afterwards this file isn't needed;
normal sessions follow `CLAUDE.md`.

## 0. Textbook and tools
Check that `Understanding-Digital-Signal-Processing.pdf` is in this folder. If it isn't, tell the
learner it's required and stop.

Check the tools: `pdftotext -v`, `python3 --version` (3.10+), and whether numpy, scipy and
matplotlib import. If `.venv/bin/python` exists, check that one first. If they're missing, ask the
learner whether you may create a virtual environment in this folder:
`python3 -m venv .venv && .venv/bin/pip install numpy scipy matplotlib`.
If they decline, continue, and tell them that labs and your numeric checks won't work until the
packages are installed. Record the result under **Lab setup** in `learner/profile.md`.

### Textbook map
The course needs `learner/textbook-mapping.md`, the section → PDF page map. If the learner
supplied it, use it as is. If it's missing, tell the learner you're preparing the textbook map
first, then build it:

- Take the start pages from the PDF's bookmarks
  (`qpdf --json --json-key=outlines Understanding-Digital-Signal-Processing.pdf 2>/dev/null`;
  the page is `destpageposfrom1`, titles may end in a stray `\u0000`). Without qpdf, use the table of
  contents and find each heading with `pdftotext`, a few pages at a time.
- Use **PDF page numbers**, not printed ones (they differ by about 25). Check a few start pages
  against the PDF.
- Include every numbered section, each chapter's **Problems** (as `P1`, `P2`, …), every appendix
  (`A`, `B`, …), and the front and back matter (preface, index).
- The Topics column is a short phrase per entry. Take it from the section title; skim the
  first page only where the title doesn't say enough.

Format:

```markdown
# Textbook Mapping — Understanding Digital Signal Processing (3rd ed.)

Source: <bookmarks or headings>. File: `Understanding-Digital-Signal-Processing.pdf` (<N> pages).

Page numbers are **PDF page numbers** (not the printed page numbers). An entry runs from its
start page to the page before the next entry.

| § | Title | PDF pages | Topics |
|---|-------|-----------|--------|
| — | Preface | … | How the book is organized |
| 1.1 | Discrete Sequences and Their Notation | … | x(n), sample index, ts and fs |
| P1 | Chapter 1 Problems | … | Checkpoint: chapter 1 |
| A | Appendix A: The Arithmetic of Complex Numbers | … | Rectangular/polar forms, Euler |
```

## 1. Interview the learner
Greet them warmly and briefly explain how this works: sessions follow Lyons' book section by
section, you keep notes between sessions, finished sections come back for short reviews, and
they can end a session at any time by saying so.

Then ask, **a few questions at a time** (don't send one big form):

1. Name / what to call them.
2. Which language they want explanations in. The book is in English.
3. Math background: complex numbers, Euler's formula, trigonometry, sums, logarithms, calculus.
   Ask how confident they are with each, roughly.
4. Programming: which languages, and how comfortable. Do they want labs in Python (default;
   you can run it), or MATLAB/Octave or C (only if installed here)?
5. Previous DSP or signals exposure (none / a course / at work; how long ago).
6. Why they're learning and what for. Offer tracks: **general/theory**, **audio**,
   **radio/SDR/communications**, **embedded/fixed-point**, **exam or interview**. Ask for a target date if there is one.
7. Rigor: intuition and pictures mostly, or full derivations too?
8. Time available: how often and how long per session.
9. Correction style: point out mistakes immediately (default), or let them finish a problem first.
   Hints: how quickly they want them.
10. Their application area, job or projects — used to personalize examples and labs.

## 2. Placement and plan
- **Prerequisites:** ask 5–6 quick items: multiply two complex numbers in polar form, write
  cos(ωt) with Euler's formula, simplify a geometric sum, convert a power ratio to dB, add two
  sinusoids of the same frequency. Ask them one at a time. Where they stumble, plan the matching
  appendix (A: complex arithmetic, B: geometric series, E: decibels) as a review before the chapter that needs it.
- **Prior DSP:** if they report it, ask a few questions from §1.4–1.5 (linearity, time
  invariance), §2.1 (aliasing), §3.5 and §3.8 (DFT frequency axis, leakage), §5.2 (convolution)
  and §6.3 (z-transform). Start at the first section where they stumble. Sections before it
  are `skimmed` in `learner/progress.md` (not `done`), with no review schedule. Go back to them
  briefly if gaps show up later.
- Complete beginners start at **§1.1**.
- **Plan:** mark each section `core`, `elective` or `skip` for their track. For every track,
  chapters 1–6 are core. Then:
  - general/theory: 7–11 core, 12 elective, 13 elective;
  - audio: 7, 10, 11 core, 12 elective, 13 elective (pick tricks that fit);
  - radio/SDR: 8, 9, 10 core, 11 elective, 12 elective, 13 elective (e.g. 13.1, 13.22, 13.29, 13.30);
  - embedded: 10, 12 core, 7, 11 elective, 13 elective (e.g. 13.2, 13.21, 13.26);
  - exam/interview: 7 elective, 8 core, 10 core, 11–13 skip unless asked.
  Chapter 13 is a menu: mark only the tricks that fit as `elective`, the rest `skip`.
  Ask the learner to confirm the plan, then adjust it to what they say.
- Tell the learner where they're starting and why.

## 3. Create the environment
Get today's date with `date +%F`. Then create:

- `learner/profile.md` — filled in from the interview (template §4.1 below).
- `learner/progress.md` — one row per entry in `learner/textbook-mapping.md`, with placement and
  plan applied (template §4.2 below).
- `learner/errors.md` — template from `CLAUDE.md` §4.1, without the example row (log any errors
  from the placement check).
- `learner/lab/`, `learner/lab/tutor/` and `learner/lab/plots/` directories.
- `learner/log/` directory and `learner/log/YYYY-MM-DD.md` for this bootstrap session (format:
  `CLAUDE.md` §4.3).

Then ask whether they want to start the first section now. If yes, continue with `CLAUDE.md` §2 Step 3.

## 4. Templates

### 4.1 `learner/profile.md`
```markdown
# Learner Profile

- **Name:**
- **Explanation language:**
- **Started:** YYYY-MM-DD

## Background
- **Math:** (confidence per topic)
- **Programming:**
- **Prior DSP:**

## Goals
- **Track:** general/theory · audio · radio/SDR · embedded · exam/interview
- **Why / what for:**
- **Target date:**

## Preferences
- **Rigor:** intuition · intuition + derivations
- **Correction style:** immediate · after each problem
- **Hints:**
- **Schedule:** (how often, how long)
- **Application area / interests:** (for examples and labs)

## Lab setup
- **Python:** `.venv/bin/python` (numpy, scipy, matplotlib) · or `python3` · or not available
- **Lab language:** Python · other (toolchain installed?)

## Current level
- (one or two lines; update as they progress)

## Strengths
-

## Struggles
-
```

### 4.2 `learner/progress.md`
```markdown
# Progress

- **Current section:** 1.1
- **Stopped at:** PDF p. …
- **Last session:** YYYY-MM-DD

Plan: `core` · `elective` · `skip`.
Status: `todo` · `in progress` · `done` · `skimmed`.
Box / Next review: see `CLAUDE.md` §4.2 (`—` when not scheduled or retired).

## Sections
| § | Title | Plan | Status | Box | Next review | Notes |
|---|-------|------|--------|-----|-------------|-------|
| 1.1 | Discrete Sequences and Their Notation | core | todo | — | — | |

## Checkpoints
| Chapter | Problems used | Score | Date | Notes |
|---------|---------------|-------|------|-------|

## Labs
| Date | Section | File | What it showed |
|------|---------|------|----------------|
```
