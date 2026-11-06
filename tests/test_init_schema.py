import importlib.util
import sqlite3
import sys
import unittest

from helpers import SCRIPT, VocabTestCase


class TestInit(VocabTestCase):
    seed = False

    def test_creates_empty_db_with_default_intervals(self):
        out = self.ok("init")
        self.assertEqual(out, f"ready: {self.db}\n")
        self.assertEqual(self.count(), 0)
        self.assertEqual([tuple(r) for r in self.sql("SELECT box, days FROM intervals ORDER BY box")],
                         [(1, 1), (2, 3), (3, 7), (4, 14), (5, 30)])

    def test_creates_missing_parent_db_file_only_via_init(self):
        self.fails("due")
        self.assertFalse(self.db.exists())

    def test_init_creates_missing_parent_folder(self):
        db = self.tmp / "learner" / "nested" / "vocab.db"
        self.ok("init", db=db)
        self.assertTrue(db.exists())

    def test_only_init_creates_parent_folder(self):
        db = self.tmp / "learner" / "vocab.db"
        self.fails("due", db=db)
        self.assertFalse(db.parent.exists())


class TestInitOnExistingDb(VocabTestCase):
    def test_keeps_words(self):
        before = self.snapshot()
        self.ok("init")
        self.assertEqual(self.snapshot(), before)

    def test_keeps_custom_intervals(self):
        self.sql("UPDATE intervals SET days = 5 WHERE box = 2")
        self.ok("init")
        self.assertEqual(self.sql("SELECT days FROM intervals WHERE box = 2")[0][0], 5)


class TestSchemaConstraints(VocabTestCase):
    def assertRejected(self, query, params=()):
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql(query, params)

    def test_box_range(self):
        self.assertRejected("UPDATE vocab SET box = 7 WHERE spanish = 'el tren'")
        self.assertRejected("UPDATE vocab SET box = 0 WHERE spanish = 'el tren'")

    def test_mastered_iff_no_date(self):
        self.assertRejected("UPDATE vocab SET box = 6 WHERE spanish = 'el tren'")
        self.assertRejected("UPDATE vocab SET next_review = NULL WHERE spanish = 'el tren'")
        self.assertRejected("UPDATE vocab SET next_review = '2026-11-01' WHERE spanish = 'el café'")

    def test_spanish_unique_and_required(self):
        self.assertRejected("INSERT INTO vocab (spanish, english, added, box, next_review)"
                            " VALUES ('el tren', 'x', '2026-10-31', 1, '2026-11-01')")
        self.assertRejected("INSERT INTO vocab (spanish, english, added, box, next_review)"
                            " VALUES (NULL, 'x', '2026-10-31', 1, '2026-11-01')")

    def test_interval_must_be_positive(self):
        self.assertRejected("UPDATE intervals SET days = 0 WHERE box = 1")


class TestFold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("vocab", SCRIPT)
        cls.vocab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.vocab)

    def test_strips_accents_and_lowercases(self):
        f = self.vocab.fold
        self.assertEqual(f("Él AVIÓN"), "el avion")
        self.assertEqual(f("niño pingüino"), "nino pinguino")
        self.assertEqual(f("¿Qué?"), "¿que?")

    def test_none_is_empty(self):
        self.assertEqual(self.vocab.fold(None), "")

    def test_contains_escapes_like_wildcards(self):
        c = self.vocab.contains
        self.assertEqual(c("Año"), "%ano%")
        self.assertEqual(c("50%_x"), "%50\\%\\_x%")
        self.assertEqual(c("a\\b"), "%a\\\\b%")


if __name__ == "__main__":
    unittest.main()
