"""Integration tests: jupyter/wait_answer.py against a real, throwaway JupyterLab.

Skipped when the venv packages (JupyterLab, jupyter-collaboration, jupyter-nbmodel-client)
aren't installed. Run with the venv's Python: .venv/bin/python -m unittest discover -s tests
"""

import unittest

from helpers import Lab, Watcher, have_jupyter, learner, run_code, shift_enter, type_into_last

NOTEBOOK_CELLS = [("q1", "markdown", "**Q1.** Compute X(1) for x = [1, 2, 3, 4]."),
                  ("a1", "markdown", "")]


@unittest.skipUnless(have_jupyter(), "needs JupyterLab and jupyter-nbmodel-client (the tutor's .venv)")
class WatcherAgainstJupyterLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = Lab().start()

    @classmethod
    def tearDownClass(cls):
        cls.lab.stop()

    def notebook(self):
        # one notebook per test, so the tests don't depend on each other
        return self.lab.write_notebook(f"learner/lab/{self._testMethodName}.ipynb", NOTEBOOK_CELLS)

    def watch(self, path, timeout=30):
        w = Watcher(self.lab.url, self.lab.token, path, timeout=timeout)
        self.addCleanup(w.kill)
        self.assertTrue(w.wait_until_waiting(), f"watcher didn't start: {w.stderr}")
        return w

    def test_answer_then_shift_enter(self):
        path = self.notebook()
        w = self.watch(path)
        learner(self.lab, path, type_into_last("X(1) = −2 + 2j"))
        self.assertTrue(w.running_after(1.5), "typing alone must not count as a submission")
        learner(self.lab, path, shift_enter)
        code, out, err = w.finish()
        self.assertEqual(code, 0, err)
        self.assertIn("ANSWER SUBMITTED", out)
        self.assertIn("--- cell 1 (markdown)\nX(1) = −2 + 2j", out)

    def test_running_a_code_cell(self):
        path = self.notebook()
        w = self.watch(path)
        learner(self.lab, path, run_code("print(sum(range(4)))", "6\n", count=5))
        code, out, err = w.finish()
        self.assertEqual(code, 0, err)
        self.assertIn("(code, ran)", out)
        self.assertIn("print(sum(range(4)))", out)
        self.assertIn("--- output\n6", out)

    def test_timeout(self):
        path = self.notebook()
        w = self.watch(path, timeout=2)
        code, out, err = w.finish()
        self.assertEqual(code, 2, err)
        self.assertIn("TIMED OUT", out)

    def test_missing_notebook(self):
        w = Watcher(self.lab.url, self.lab.token, "learner/lab/does-not-exist.ipynb", timeout=10)
        self.addCleanup(w.kill)
        code, out, err = w.finish(timeout=45)
        self.assertEqual(code, 1)
        self.assertIn("didn't open", err)
        self.assertNotIn("Traceback", err)

    def test_wrong_token(self):
        path = self.notebook()
        w = Watcher(self.lab.url, "not-the-token", path, timeout=10)
        self.addCleanup(w.kill)
        code, out, err = w.finish(timeout=45)
        self.assertEqual(code, 1)
        self.assertIn("Can't open", err)


@unittest.skipUnless(have_jupyter(), "needs JupyterLab and jupyter-nbmodel-client (the tutor's .venv)")
class WatcherWithoutJupyterLab(unittest.TestCase):
    def test_server_not_running(self):
        lab = Lab()  # never started: nothing listens on its port
        self.addCleanup(lab.stop)
        w = Watcher(lab.url, lab.token, "learner/lab/x.ipynb", timeout=10)
        self.addCleanup(w.kill)
        code, out, err = w.finish()
        self.assertEqual(code, 1)
        self.assertIn("Can't open", err)
        self.assertNotIn("Traceback", err)

    def test_server_crashes_while_waiting(self):
        with Lab() as lab:
            path = lab.write_notebook("learner/lab/crash.ipynb", NOTEBOOK_CELLS)
            w = Watcher(lab.url, lab.token, path, timeout=60)
            self.addCleanup(w.kill)
            self.assertTrue(w.wait_until_waiting(), w.stderr)
            lab.kill()
            code, out, err = w.finish(timeout=20)
        self.assertEqual(code, 1)
        self.assertIn("connection to JupyterLab closed", err)


if __name__ == "__main__":
    unittest.main()
