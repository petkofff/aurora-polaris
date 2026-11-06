# Bootstrap — first launch only

Run this once, when `learner/profile.md` doesn't exist yet. Afterwards this file isn't needed;
normal sessions follow `CLAUDE.md`.

## 0. Textbook map
Check that `Madrigal's Magic Key to Spanish.pdf` is in this folder. If it isn't, tell the learner
it's required and stop.

The course needs `learner/textbook-mapping.md`, the lesson → PDF page map. If the learner supplied
it, use it as is. If it's missing, tell the learner you're preparing the textbook map first, then
build it:

- Take the lesson start pages from the PDF's bookmarks if it has them
  (`qpdf --json --json-key=outlines "Madrigal's Magic Key to Spanish.pdf"`, when qpdf is installed).
  Otherwise find each lesson's heading with `pdftotext`, a few pages at a time.
- Use **PDF page numbers**, not printed ones. Check a few start pages against the PDF.
- Include every lesson (1–45), every **Test Your Progress** checkpoint (T1, T2, …), and the
  front and back matter (pronunciation key, expressions, vocabulary, index).
- For topics, skim only the first page or two of each lesson; a short phrase per lesson is enough.

Format:

```markdown
# Textbook Mapping — Madrigal's Magic Key to Spanish

Source: <bookmarks or headings>. File: `Madrigal's Magic Key to Spanish.pdf` (<N> pages).

Page numbers are **PDF page numbers** (not the printed page numbers). A lesson runs from its
start page to the page before the next entry.

| # | Lesson | PDF pages | Topics |
|---|--------|-----------|--------|
| — | Pronunciation Key + Preface | 4–18 | Spanish sounds; how the method works |
| 1 | Uno | 19–39 | Cognates ending in -or, -al, -ble…; *es / no es*; questions by inversion |
| T1 | Test Your Progress | … | Checkpoint: lessons 1–11 |
```

## 1. Interview the learner
Greet them warmly and briefly explain how this works: sessions follow the Madrigal textbook,
you keep notes between sessions, and they can end a session at any time by saying so.

Then ask, **a few questions at a time** (don't send one big form):

1. Name / what to call them.
2. Native language and other languages they speak. The textbook explains in English; ask which
   language they want explanations in (English, their native language, or a mix).
3. Previous Spanish exposure (none / some words / studied before; how long ago).
4. Why they're learning, and concrete goals (e.g. travel in 6 months, conversation, reading,
   an exam). Ask for a rough target date if there is one.
5. Preferred variety: Spain or Latin America (affects vosotros, ceceo, some vocabulary).
   The book is mostly neutral/Latin American and uses *usted* throughout.
6. Time available: how often and how long per session.
7. Correction style: correct every mistake immediately (default), or let them finish and
   correct at the end of each exercise.
8. Can they type Spanish characters (á é í ó ú ñ ü ¿ ¡)? If not, accept plain letters
   but still show the correct spelling.
9. Interests/hobbies/job — used to personalize example sentences.

## 2. Placement
- Complete beginners start at **Lesson 1**.
- If they report prior study, do a short placement check (5–10 quick items drawn from
  lessons 1, 6, 14, 22, 31 — see `learner/textbook-mapping.md`): translate a sentence, conjugate a verb, answer a
  question in Spanish. Pick the first lesson where they stumble. Lessons before it are marked
  `skimmed` in `learner/progress.md` (not `done`) — revisit them briefly if gaps show up later.
- Tell the learner where they're starting and why.

## 3. Create the environment
Get today's date with `date +%F`. Then create:

- `learner/profile.md` — filled in from the interview (template §4.1 below).
- `learner/progress.md` — one row per entry in `learner/textbook-mapping.md`, with placement applied (template §4.2 below).
- `learner/errors.md` — template from `CLAUDE.md` §4.1, without the example row (log any errors from the placement check).
- `learner/vocab.db` — run `./vocab.py init` (see `CLAUDE.md` §4.2); add any words from the placement check with `./vocab.py add`.
- `learner/log/` directory and `learner/log/YYYY-MM-DD.md` for this bootstrap session (format: `CLAUDE.md` §4.3).

Then ask whether they want to start the first lesson now. If yes, continue with `CLAUDE.md` §2 Step 2.

## 4. Templates

Keep all files in Markdown. Dates always `YYYY-MM-DD`.

### 4.1 `learner/profile.md`
```markdown
# Learner Profile

## Basics
- Name:
- Native language:
- Other languages:
- Explanation language / current Spanish ratio: e.g. English, ~10% Spanish
- Variety: Spain | Latin America | neutral
- Can type Spanish characters: yes | no
- Started: YYYY-MM-DD

## Goals
- Why learning:
- Concrete goals (with target dates):

## Schedule & preferences
- Sessions: e.g. 3×/week, 45 min
- Correction style: immediate | end of exercise
- Interests (for examples):
- Other preferences:

## Current level
- Estimated CEFR: A0 | A1 | A2 | B1 | …
- Current lesson: N (see progress.md)
- Summary: 1–3 sentences on what they can do now.

## Strengths
-

## Common struggles
- (keep in sync with active patterns in errors.md; add non-error struggles too,
  e.g. "gets discouraged by long lists", "confuses ser/estar under pressure")

## Notes
- Anything else useful for the next tutor session.
```

### 4.2 `learner/progress.md`
```markdown
# Textbook Progress — Madrigal's Magic Key to Spanish

**Current lesson:** 1 — stopped at PDF p. 19 (start)
**Sessions so far:** 0

Status values: `todo` · `in progress` · `done` · `skimmed` (placement-skipped) · `review` (needs revisiting)

| # | Lesson | PDF pages | Status | Started | Finished | Notes |
|---|--------|-----------|--------|---------|----------|-------|
| 1 | Uno | 19–39 | todo | | | |
| … one row per entry in textbook-mapping.md, including T1–T5 … |

## Checkpoint scores
| Test | Date | Score | Weak areas |
|------|------|-------|------------|
```
