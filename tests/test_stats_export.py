import unittest

from helpers import FIXTURE, VocabTestCase

HEADER = "| Spanish | English | Type | Lesson | Added | Box | Next review | Notes |"


def parse_export(out):
    """Markdown table → list of 8-cell rows (header and separator dropped)."""
    lines = out.splitlines()
    return [[c.strip() for c in line.strip("|").split("|")] for line in lines[2:]]


def expected_cells(fx):
    _, sp, en, ty, le, added, box, nxt, notes = fx
    return [sp, en, ty, le, added, "M" if box == 6 else str(box), nxt or "—", notes.replace("|", "/")]


class TestStats(VocabTestCase):
    def test_output(self):
        self.assertEqual(self.ok("stats").splitlines(), [
            "Total words: 12 · due today (2026-10-31): 9 · mastered: 1",
            "By box: 1: 5 · 2: 3 · 3: 1 · 4: 1 · 5: 1",
            "By lesson: 4: 7 · 5: 1 · 6: 2 · 7: 1 · placement: 1",
        ])

    def test_due_count_follows_today(self):
        self.assertIn("due today (2026-11-01): 10", self.ok("stats", today="2026-11-01"))

    def test_empty_db(self):
        self.sql("DELETE FROM vocab")
        self.assertEqual(self.ok("stats").splitlines()[:2], [
            "Total words: 0 · due today (2026-10-31): 0 · mastered: 0",
            "By box: 1: 0 · 2: 0 · 3: 0 · 4: 0 · 5: 0",
        ])


class TestExport(VocabTestCase):
    def test_header(self):
        lines = self.ok("export").splitlines()
        self.assertEqual(lines[0], HEADER)
        self.assertTrue(set(lines[1]) <= set("|-"))

    def test_default_hides_mastered(self):
        rows = parse_export(self.ok("export"))
        self.assertEqual([r[0] for r in rows], [f[1] for f in FIXTURE if f[6] != 6])

    def test_all_matches_db_exactly(self):
        self.assertEqual(parse_export(self.ok("export", "--all")), [expected_cells(f) for f in FIXTURE])

    def test_mastered_shown_as_M_and_dash(self):
        rows = {r[0]: r for r in parse_export(self.ok("export", "--all"))}
        self.assertEqual(rows["el café"][5:7], ["M", "—"])

    def test_every_line_has_8_columns(self):
        for line in self.ok("export", "--all").splitlines():
            self.assertEqual(line.count("|"), 9, line)

    def test_pipe_in_cell_escaped(self):
        rows = {r[0]: r for r in parse_export(self.ok("export"))}
        self.assertEqual(rows["-ty → -dad"][7], "always feminine / stress -DAD")

    def test_empty_cells_render_as_single_space(self):
        line = next(l for l in self.ok("export").splitlines() if l.startswith("| el tren |"))
        self.assertTrue(line.endswith("| 2026-10-08 | |"), line)

    def test_empty_db(self):
        self.sql("DELETE FROM vocab")
        self.assertEqual(len(self.ok("export", "--all").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
