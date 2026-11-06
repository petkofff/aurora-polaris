# Aurora Polaris

A suite of language tutors that run in [Claude Code](https://claude.com/claude-code). Each tutor
follows one textbook, lesson by lesson, and remembers the learner between sessions through notes
it keeps in a private folder: what they've covered, the mistakes they repeat, and the vocabulary
that's due for review.

## Tutors

| Tutor | Language | Textbook |
|---|---|---|
| [`Madrigal-Spanish-Tutor`](Madrigal-Spanish-Tutor/) | Spanish | *Madrigal's Magic Key to Spanish* (Margarita Madrigal, 1951) |

## Getting started

```sh
git clone https://github.com/petkofff/aurora-polaris.git
cd aurora-polaris/Madrigal-Spanish-Tutor
claude
```

Each tutor's README lists what it needs. The textbooks aren't included: you supply your own copy
and save it in the tutor's folder. On first launch, the tutor interviews you, places you in the
book, and creates your learner files.

Always start Claude Code **inside a tutor's folder**. That's where its instructions
(`CLAUDE.md`) and permissions (`.claude/settings.json`) are.

## How a tutor is laid out

Every tutor is a self-contained folder:

| File | What it is |
|---|---|
| `CLAUDE.md` | The tutor's instructions: session workflow, teaching rules, file formats |
| `bootstrap.md` | First-launch interview, placement and setup |
| `README.md` | Requirements and usage for this tutor |
| `.claude/settings.json` | Commands the tutor may run without a permission prompt |
| `learner/` | The learner's notes. Created by the tutor, never committed here |

A tutor may add its own tools, such as the Spanish tutor's `vocab.py` and its tests.

## Your progress stays private

`learner/` and textbook PDFs are ignored by this repo, so your notes can't end up in a commit or
a pull request. To back them up, make a tutor's `learner/` folder its own private git repo. The
tutor's README shows how.

## Adding a tutor

- Name the folder `<Author>-<Language>-Tutor`, after the textbook's author.
- Keep everything the tutor needs inside its folder, and every path in its instructions relative
  to that folder.
- Keep all learner data in `learner/`. Have the bootstrap create it, including anything built
  from the user's copy of the book, such as a lesson-to-page map.
- Don't add a `CLAUDE.md` at the root. Claude Code also loads `CLAUDE.md` files from parent
  folders, so it would apply to every tutor.
- Add the tutor to the table above.

## Development

To work on the tutors themselves, start Claude Code at the root of the repo and ask it to read
[`DEVELOPMENT.md`](DEVELOPMENT.md). It isn't a `CLAUDE.md`, so it never loads into a tutoring
session.

## License

Copyright (C) 2026 petkofff

This program is free software; you can redistribute it and/or modify it under the terms of the
GNU General Public License, version 2 only (`GPL-2.0-only`). See [`LICENSE`](LICENSE).

The textbooks are not covered by this license and are not included.
