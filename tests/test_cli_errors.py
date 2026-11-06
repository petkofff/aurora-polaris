import unittest

from helpers import VocabTestCase


class TestCliErrors(VocabTestCase):
    def test_missing_db(self):
        err = self.fails("due", db=self.tmp / "nope.db")
        self.assertIn("not found", err)
        self.assertIn("vocab.py init", err)
        self.assertFalse((self.tmp / "nope.db").exists(), "a missing DB must not be created silently")

    def test_no_command(self):
        self.fails(code=2)

    def test_unknown_command(self):
        self.fails("frobnicate", code=2)

    def test_non_integer_limit(self):
        self.fails("due", "ten", code=2)

    def test_invalid_vocab_today(self):
        err = self.fails("due", today="31/10/2026")
        self.assertIn("VOCAB_TODAY must be YYYY-MM-DD", err)
        self.assertNotIn("Traceback", err)

    def test_help_lists_commands(self):
        out = self.ok("--help")
        for cmd in ("due", "review", "add", "find", "edit", "delete", "stats", "export", "init"):
            self.assertIn(cmd, out)

    def test_real_date_used_without_override(self):
        from datetime import date
        out = self.ok("due", today=None)
        self.assertTrue(out.startswith(f"Due on {date.today().isoformat()}:"))


if __name__ == "__main__":
    unittest.main()
