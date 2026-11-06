import unittest

from helpers import VocabTestCase


def found(out):
    return [line.split(" | ")[0] for line in out.splitlines()[1:]]


class TestFind(VocabTestCase):
    def test_by_spanish(self):
        self.assertEqual(found(self.ok("find", "tren")), ["el tren"])

    def test_by_english(self):
        self.assertEqual(found(self.ok("find", "airplane")), ["el avión"])

    def test_in_notes(self):
        self.assertEqual(found(self.ok("find", "cuidad")), ["la ciudad"])

    def test_accent_insensitive_both_ways(self):
        self.assertEqual(found(self.ok("find", "estacion")), ["la estación"])
        self.assertEqual(found(self.ok("find", "TELEFONO")), ["hablé por teléfono"])
        # accent in the wrong place still matches, since all accents are folded away
        self.assertEqual(found(self.ok("find", "telefóno")), ["hablé por teléfono"])

    def test_case_insensitive(self):
        self.assertEqual(found(self.ok("find", "THE SOUP")), ["la sopa"])

    def test_multiple_matches_in_id_order(self):
        self.assertEqual(found(self.ok("find", "dad")), ["la ciudad", "-ty → -dad"])

    def test_header_and_no_matches(self):
        self.assertEqual(self.ok("find", "xyz"), "0 match(es) for 'xyz'\n")
        self.assertTrue(self.ok("find", "tren").startswith("1 match(es) for 'tren'"))

    def test_sql_wildcards_are_literal(self):
        for term in ["%", "_", "el_tren", "\\"]:
            with self.subTest(term=term):
                self.assertEqual(found(self.ok("find", term)), [])

    def test_literal_percent_found(self):
        self.ok("add", "el cien por ciento", "100%", "phrase", "8")
        self.assertEqual(found(self.ok("find", "100%")), ["el cien por ciento"])

    def test_includes_mastered(self):
        self.assertIn("mastered", self.ok("find", "café"))


class TestEdit(VocabTestCase):
    def test_each_field(self):
        cases = {"--english": ("english", "the railway train"), "--type": ("type", "noun"),
                 "--lesson": ("lesson", "9"), "--notes": ("notes", "new note")}
        for flag, (col, value) in cases.items():
            with self.subTest(flag=flag):
                self.ok("edit", "el tren", flag, value)
                self.assertEqual(self.row("el tren")[col], value)

    def test_clear_notes(self):
        self.ok("edit", "la ciudad", "--notes", "")
        self.assertEqual(self.row("la ciudad")["notes"], "")

    def test_keeps_review_state_and_added_date(self):
        before = self.row("la ciudad")
        self.ok("edit", "la ciudad", "--english", "the town", "--notes", "x")
        after = self.row("la ciudad")
        for col in ("id", "box", "next_review", "added"):
            self.assertEqual(after[col], before[col], col)

    def test_rename_then_lookup_by_new_name(self):
        self.ok("edit", "el tren", "--spanish", "el ferrocarril")
        self.assertIsNone(self.row("el tren"))
        self.ok("review", "el ferrocarril", "right")
        self.assertEqual(self.state("el ferrocarril"), (2, "2026-11-03"))

    def test_rename_to_accent_variant_of_itself_allowed(self):
        self.ok("edit", "el tren", "--spanish", "el trén")
        self.assertIsNotNone(self.row("el trén"))

    def test_rename_onto_existing_word_rejected(self):
        before = self.snapshot()
        for target in ["la sopa", "el avion"]:
            with self.subTest(target=target):
                self.assertIn("already", self.fails("edit", "el tren", "--spanish", target))
        self.assertEqual(self.snapshot(), before)

    def test_no_changes_rejected(self):
        self.assertIn("nothing to change", self.fails("edit", "el tren"))

    def test_unknown_word(self):
        self.assertIn("no word", self.fails("edit", "el gato", "--english", "cat"))

    def test_output(self):
        out = self.ok("edit", "el tren", "--english", "the railway")
        self.assertEqual(out, "updated: el tren | the railway | noun m. | L4 | box 1, due 2026-10-08\n")


class TestDelete(VocabTestCase):
    def test_removes_only_target(self):
        before = [r for r in self.snapshot() if r[1] != "la sopa"]
        out = self.ok("delete", "la sopa")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(out, "deleted: la sopa | the soup | noun f. | L4 | box 1, due 2026-10-08\n")

    def test_accent_insensitive(self):
        self.ok("delete", "la cancion")
        self.assertIsNone(self.row("la canción"))

    def test_unknown_word(self):
        self.fails("delete", "el gato")
        self.assertEqual(self.count(), 12)


if __name__ == "__main__":
    unittest.main()
