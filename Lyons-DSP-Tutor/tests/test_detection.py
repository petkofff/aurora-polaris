"""Unit tests for the submission logic of jupyter/wait_answer.py. No Jupyter needed."""

import contextlib
import io
import unittest

from helpers import baseline_of, cell

import wait_answer as wa

QUESTION = cell("q1", "**Q1.** Compute X(1).")
ANSWER = cell("a1", "")


class FindSubmission(unittest.TestCase):
    def setUp(self):
        self.before = [QUESTION, ANSWER]
        self.base = baseline_of(self.before)

    def test_nothing_changed(self):
        self.assertIsNone(wa.find_submission(self.base, self.before))

    def test_typing_alone_is_not_a_submission(self):
        after = [QUESTION, cell("a1", "X(1) = −2 + 2j")]
        self.assertIsNone(wa.find_submission(self.base, after))

    def test_answer_then_shift_enter(self):
        after = [QUESTION, cell("a1", "X(1) = −2 + 2j"), cell("new", "", type="code")]
        self.assertEqual(wa.find_submission(self.base, after), [1])

    def test_shift_enter_on_an_empty_answer_is_not_a_submission(self):
        after = [QUESTION, ANSWER, cell("new", "", type="code")]
        self.assertIsNone(wa.find_submission(self.base, after))

    def test_whitespace_only_answer_is_not_a_submission(self):
        after = [QUESTION, cell("a1", "  \n"), cell("new", "", type="code")]
        self.assertIsNone(wa.find_submission(self.base, after))

    def test_new_answer_cell_then_shift_enter(self):
        after = [QUESTION, ANSWER, cell("mine", "my answer"), cell("new", "", type="code")]
        self.assertEqual(wa.find_submission(self.base, after), [2])

    def test_new_answer_cell_without_shift_enter(self):
        after = [QUESTION, ANSWER, cell("mine", "my answer")]
        self.assertIsNone(wa.find_submission(self.base, after))

    def test_running_a_code_cell(self):
        after = [QUESTION, ANSWER, cell("c1", "print(6)", type="code", count=1)]
        self.assertEqual(wa.find_submission(self.base, after), [2])

    def test_rerunning_an_existing_code_cell(self):
        before = [QUESTION, cell("c1", "print(6)", type="code", count=3)]
        after = [QUESTION, cell("c1", "print(6)", type="code", count=4)]
        self.assertEqual(wa.find_submission(baseline_of(before), after), [1])

    def test_editing_code_without_running_or_shift_enter(self):
        before = [QUESTION, cell("c1", "print(6)", type="code", count=3)]
        after = [QUESTION, cell("c1", "print(7)", type="code", count=3)]
        self.assertIsNone(wa.find_submission(baseline_of(before), after))

    def test_deleting_a_cell_is_not_a_submission(self):
        after = [ANSWER]
        self.assertIsNone(wa.find_submission(self.base, after))

    def test_reports_every_changed_cell(self):
        after = [cell("q1", "edited question"), cell("a1", "answer"), cell("new", "", type="code")]
        self.assertEqual(wa.find_submission(self.base, after), [0, 1])


class TextOutputs(unittest.TestCase):
    def test_stream_as_string_and_list(self):
        outs = [{"output_type": "stream", "name": "stdout", "text": "a\n"},
                {"output_type": "stream", "name": "stdout", "text": ["b", "c\n"]}]
        self.assertEqual(wa.text_outputs(outs), "a\nbc")

    def test_result_error_and_image(self):
        outs = [{"output_type": "execute_result", "data": {"text/plain": "42"}},
                {"output_type": "display_data", "data": {"image/png": "iVBOR…", "text/plain": "<Figure>"}},
                {"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero"}]
        text = wa.text_outputs(outs)
        self.assertIn("42", text)
        self.assertIn("<Figure>", text)
        self.assertIn("[image output", text)
        self.assertIn("ZeroDivisionError: division by zero", text)

    def test_truncates_long_output(self):
        outs = [{"output_type": "stream", "name": "stdout", "text": "x" * (wa.MAX_OUTPUT + 500)}]
        text = wa.text_outputs(outs)
        self.assertTrue(text.endswith("…[truncated]"))
        self.assertEqual(len(text), wa.MAX_OUTPUT + len(" …[truncated]"))


class Report(unittest.TestCase):
    def render(self, baseline, cells, indices):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wa.report(baseline, cells, indices)
        return buf.getvalue()

    def test_markdown_answer(self):
        cells = [QUESTION, cell("a1", "X(1) = −2 + 2j"), cell("new", "", type="code")]
        out = self.render(baseline_of([QUESTION, ANSWER]), cells, [1])
        self.assertTrue(out.startswith("ANSWER SUBMITTED"))
        self.assertIn("--- cell 1 (markdown)\nX(1) = −2 + 2j", out)
        self.assertIn("The notebook now has 3 cells", out)

    def test_code_cell_that_ran(self):
        outs = [{"output_type": "stream", "name": "stdout", "text": "6\n"}]
        cells = [QUESTION, cell("c1", "print(6)", type="code", count=1, outputs=outs)]
        out = self.render(baseline_of([QUESTION]), cells, [1])
        self.assertIn("--- cell 1 (code, ran)", out)
        self.assertIn("--- output\n6", out)

    def test_code_cell_edited_but_not_rerun(self):
        outs = [{"output_type": "stream", "name": "stdout", "text": "6\n"}]
        before = [cell("c1", "print(6)", type="code", count=3, outputs=outs)]
        after = [cell("c1", "print(7)", type="code", count=3, outputs=outs), cell("new", "", type="code")]
        out = self.render(baseline_of(before), after, [0])
        self.assertIn("(code, edited, not re-run)", out)
        self.assertIn("--- output (from an earlier run, may be stale)", out)

    def test_skips_empty_cells(self):
        cells = [cell("a1", ""), cell("a2", "answer"), cell("new", "", type="code")]
        out = self.render({}, cells, [0, 1])
        self.assertNotIn("--- cell 0", out)
        self.assertIn("--- cell 1", out)


class CellState(unittest.TestCase):
    def test_source_as_list(self):
        self.assertEqual(wa.cell_state({"source": ["a\n", "b"], "execution_count": 2}), ("a\nb", 2))

    def test_markdown_has_no_count(self):
        self.assertEqual(wa.cell_state({"source": "text"}), ("text", None))


if __name__ == "__main__":
    unittest.main()
