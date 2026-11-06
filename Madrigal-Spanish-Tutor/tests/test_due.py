import unittest

from helpers import DUE_ORDER, VocabTestCase


def listed(out):
    """Spanish words from `due` output (skipping the header line)."""
    return [line.split(" | ")[0] for line in out.splitlines()[1:]]


class TestDue(VocabTestCase):
    def test_header_counts_all_due_words(self):
        out = self.ok("due")
        self.assertEqual(out.splitlines()[0],
                         "Due on 2026-10-31: 9 word(s); showing 9 (most overdue first)")

    def test_order_most_overdue_then_lowest_box_then_oldest(self):
        self.assertEqual(listed(self.ok("due", "20")), DUE_ORDER)

    def test_default_limit_is_10(self):
        self.ok("add", "el gato", "the cat", "noun m.", "8")
        self.ok("add", "el perro", "the dog", "noun m.", "8")
        out = self.ok("due", today="2026-11-01")  # 9 + el niño + 2 new = 12 due
        self.assertTrue(out.startswith("Due on 2026-11-01: 12 word(s); showing 10"))
        self.assertEqual(len(listed(out)), 10)

    def test_custom_limit(self):
        out = self.ok("due", "3")
        self.assertIn("9 word(s); showing 3", out)
        self.assertEqual(listed(out), DUE_ORDER[:3])

    def test_due_today_included_tomorrow_excluded(self):
        words = listed(self.ok("due", "50"))
        self.assertIn("la estación", words)   # due 2026-10-31 (today)
        self.assertNotIn("el niño", words)    # due 2026-11-01 (tomorrow)
        self.assertNotIn("la canción", words)

    def test_tomorrow_brings_in_next_day_words(self):
        self.assertIn("el niño", listed(self.ok("due", "50", today="2026-11-01")))

    def test_mastered_never_due(self):
        self.assertNotIn("el café", listed(self.ok("due", "50", today="2099-01-01")))

    def test_nothing_due(self):
        out = self.ok("due", today="2026-01-01")
        self.assertEqual(out, "Due on 2026-01-01: 0 word(s); showing 0 (most overdue first)\n")

    def test_line_format(self):
        lines = self.ok("due", "50").splitlines()
        self.assertIn("la ciudad | the city | noun f. | L4 | box 3, due 2026-10-20"
                      " — spelling: ciu-DAD (not cuidad)", lines)
        self.assertIn("el tren | the train | noun m. | L4 | box 1, due 2026-10-08", lines)

    def test_due_does_not_modify_db(self):
        before = self.snapshot()
        self.ok("due", "50")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
