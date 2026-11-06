import unittest

from helpers import VocabTestCase


class TestReviewRight(VocabTestCase):
    def test_box_1_to_2_plus_3_days(self):
        self.ok("review", "el tren", "right")
        self.assertEqual(self.state("el tren"), (2, "2026-11-03"))

    def test_box_2_to_3_plus_7_days(self):
        self.ok("review", "el problema", "right")
        self.assertEqual(self.state("el problema"), (3, "2026-11-07"))

    def test_box_3_to_4_plus_14_days(self):
        self.ok("review", "la ciudad", "right")
        self.assertEqual(self.state("la ciudad"), (4, "2026-11-14"))

    def test_box_4_to_5_plus_30_days(self):
        self.ok("review", "la estación", "right")
        self.assertEqual(self.state("la estación"), (5, "2026-11-30"))

    def test_box_5_to_mastered(self):
        out = self.ok("review", "el avión", "right")
        self.assertEqual(self.state("el avión"), (6, None))
        self.assertEqual(out, "el avión: right — box 5 → mastered\n")

    def test_right_on_mastered_stays_mastered(self):
        self.ok("review", "el café", "right")
        self.assertEqual(self.state("el café"), (6, None))

    def test_reviewing_word_not_yet_due_still_counts(self):
        self.ok("review", "la canción", "right")  # due 2026-11-05
        self.assertEqual(self.state("la canción"), (3, "2026-11-07"))

    def test_output_line(self):
        out = self.ok("review", "el tren", "right")
        self.assertEqual(out, "el tren: right — box 1 → box 2, next 2026-11-03\n")

    def test_full_path_to_mastery(self):
        days = ["2026-10-31", "2026-11-03", "2026-11-10", "2026-11-24", "2026-12-24"]
        expected = [(2, "2026-11-03"), (3, "2026-11-10"), (4, "2026-11-24"), (5, "2026-12-24"), (6, None)]
        for day, exp in zip(days, expected):
            self.ok("review", "el tren", "right", today=day)
            self.assertEqual(self.state("el tren"), exp, f"after review on {day}")


class TestReviewWrong(VocabTestCase):
    def test_wrong_from_every_box_goes_to_box_1_tomorrow(self):
        for word in ["el tren", "el problema", "la ciudad", "la estación", "el avión", "el café"]:
            with self.subTest(word=word):
                self.ok("review", word, "wrong")
                self.assertEqual(self.state(word), (1, "2026-11-01"))

    def test_wrong_output_line(self):
        out = self.ok("review", "la ciudad", "wrong")
        self.assertEqual(out, "la ciudad: wrong — box 3 → box 1, next 2026-11-01\n")

    def test_wrong_on_mastered_reports_mastered_as_old_box(self):
        out = self.ok("review", "el café", "wrong")
        self.assertIn("box 6 → box 1", out)


class TestReviewDates(VocabTestCase):
    def test_wrong_across_year_end(self):
        self.ok("review", "el tren", "wrong", today="2026-12-31")
        self.assertEqual(self.state("el tren"), (1, "2027-01-01"))

    def test_wrong_on_leap_day_eve(self):
        self.ok("review", "el tren", "wrong", today="2028-02-28")
        self.assertEqual(self.state("el tren"), (1, "2028-02-29"))

    def test_right_across_month_end(self):
        self.ok("review", "el tren", "right", today="2026-11-29")  # +3
        self.assertEqual(self.state("el tren"), (2, "2026-12-02"))

    def test_30_days_across_year_end(self):
        self.ok("review", "la estación", "right", today="2026-12-15")
        self.assertEqual(self.state("la estación"), (5, "2027-01-14"))

    def test_custom_intervals_are_used(self):
        self.sql("UPDATE intervals SET days = 5 WHERE box = 2")
        self.ok("review", "el tren", "right")
        self.assertEqual(self.state("el tren"), (2, "2026-11-05"))


class TestReviewBatch(VocabTestCase):
    def test_several_pairs(self):
        self.ok("review", "el tren", "right", "la sopa", "wrong", "la ciudad", "right")
        self.assertEqual(self.state("el tren"), (2, "2026-11-03"))
        self.assertEqual(self.state("la sopa"), (1, "2026-11-01"))
        self.assertEqual(self.state("la ciudad"), (4, "2026-11-14"))

    def test_unknown_word_in_batch_writes_nothing(self):
        before = self.snapshot()
        err = self.fails("review", "el tren", "right", "el gato", "right")
        self.assertIn("no word 'el gato'", err)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_result_writes_nothing(self):
        before = self.snapshot()
        err = self.fails("review", "el tren", "right", "la sopa", "maybe")
        self.assertIn("must be 'right' or 'wrong'", err)
        self.assertEqual(self.snapshot(), before)

    def test_odd_argument_count(self):
        err = self.fails("review", "el tren", "right", "la sopa")
        self.assertIn("WORD RESULT pairs", err)

    def test_results_are_case_sensitive(self):
        self.fails("review", "el tren", "RIGHT")


class TestReviewLookup(VocabTestCase):
    def test_without_accents(self):
        self.ok("review", "el avion", "wrong")
        self.assertEqual(self.state("el avión"), (1, "2026-11-01"))

    def test_case_insensitive(self):
        self.ok("review", "LA ESTACION", "wrong")
        self.assertEqual(self.state("la estación"), (1, "2026-11-01"))

    def test_n_tilde_folds_to_n(self):
        self.ok("review", "el nino", "right")
        self.assertEqual(self.state("el niño"), (2, "2026-11-03"))

    def test_exact_match_wins_over_folded(self):
        self.sql("INSERT INTO vocab (spanish, english, added, box, next_review) "
                 "VALUES ('el te', 'you (wrong)', '2026-10-31', 1, '2026-11-01'),"
                 "       ('el té', 'tea', '2026-10-31', 1, '2026-11-01')")
        self.ok("review", "el té", "right")
        self.assertEqual(self.state("el té")[0], 2)
        self.assertEqual(self.state("el te")[0], 1)

    def test_ambiguous_folded_match_is_rejected(self):
        self.sql("INSERT INTO vocab (spanish, english, added, box, next_review) "
                 "VALUES ('el te', 'you (wrong)', '2026-10-31', 1, '2026-11-01'),"
                 "       ('el té', 'tea', '2026-10-31', 1, '2026-11-01')")
        before = self.snapshot()
        err = self.fails("review", "EL TE", "right")
        self.assertIn("ambiguous", err)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_word_suggests_similar(self):
        err = self.fails("review", "tren", "right")
        self.assertIn("did you mean: el tren", err)

    def test_unknown_word_without_similar(self):
        err = self.fails("review", "xyz", "right")
        self.assertIn("no word 'xyz'", err)
        self.assertNotIn("did you mean", err)

    def test_sql_wildcards_do_not_match_everything(self):
        for term in ["%", "_"]:
            with self.subTest(term=term):
                err = self.fails("review", term, "right")
                self.assertNotIn("did you mean", err)


if __name__ == "__main__":
    unittest.main()
