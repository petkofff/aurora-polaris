import unittest

from helpers import VocabTestCase


class TestAdd(VocabTestCase):
    def test_defaults(self):
        out = self.ok("add", "el gato", "the cat", "noun m.", "8")
        r = self.row("el gato")
        self.assertEqual((r["english"], r["type"], r["lesson"], r["added"], r["box"], r["next_review"], r["notes"]),
                         ("the cat", "noun m.", "8", "2026-10-31", 1, "2026-11-01", ""))
        self.assertEqual(out, "added: el gato | the cat | noun m. | L8 | box 1, due 2026-11-01\n")

    def test_notes(self):
        self.ok("add", "el gato", "the cat", "noun m.", "8", "--notes", "≠ el gallo")
        self.assertEqual(self.row("el gato")["notes"], "≠ el gallo")

    def test_box_option_uses_that_box_interval(self):
        expected = {2: "2026-11-03", 3: "2026-11-07", 4: "2026-11-14", 5: "2026-11-30"}
        for box, nxt in expected.items():
            with self.subTest(box=box):
                word = f"palabra {box}"
                self.ok("add", word, "word", "noun f.", "placement", "--box", str(box))
                self.assertEqual(self.state(word), (box, nxt))

    def test_box_6_adds_as_mastered(self):
        out = self.ok("add", "el gato", "the cat", "noun m.", "8", "--box", "6")
        self.assertEqual(self.state("el gato"), (6, None))
        self.assertIn("mastered", out)

    def test_box_out_of_range_rejected(self):
        for box in ["0", "7", "x"]:
            with self.subTest(box=box):
                self.fails("add", "el gato", "the cat", "noun m.", "8", "--box", box, code=2)
        self.assertIsNone(self.row("el gato"))

    def test_exact_duplicate_rejected(self):
        before = self.snapshot()
        err = self.fails("add", "el tren", "train", "noun m.", "8")
        self.assertIn("already exists: el tren", err)
        self.assertEqual(self.snapshot(), before)

    def test_accent_and_case_variant_duplicate_rejected(self):
        for variant in ["el avion", "EL AVIÓN", "El Avion"]:
            with self.subTest(variant=variant):
                self.fails("add", variant, "plane", "noun m.", "8")
        self.assertEqual(self.count(), 12)

    def test_quotes_and_unicode_stored_verbatim(self):
        notes = 'it\'s "fine"; DROP TABLE vocab; -- ¿¡ñü'
        self.ok("add", "¿Qué tal?", "how's it going?", "phrase", "8", "--notes", notes)
        r = self.row("¿Qué tal?")
        self.assertEqual((r["english"], r["notes"]), ("how's it going?", notes))
        self.assertEqual(self.count(), 13)

    def test_missing_arguments(self):
        self.fails("add", "el gato", "the cat", "noun m.", code=2)

    def test_uses_today(self):
        self.ok("add", "el gato", "the cat", "noun m.", "8", today="2027-03-01")
        self.assertEqual((self.row("el gato")["added"], self.state("el gato")), ("2027-03-01", (1, "2027-03-02")))


if __name__ == "__main__":
    unittest.main()
