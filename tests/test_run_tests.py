import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ruffster_test_runner", ROOT / "scripts/run-tests.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class TestRunnerShardTests(unittest.TestCase):
    def test_selects_only_the_requested_test_files(self):
        suite = RUNNER.load_suite(["test_docs_site.py", "test_windows_setup_source.py"])
        self.assertEqual(suite.countTestCases(), 41)

    def test_rejects_paths_and_non_test_files(self):
        for filename in ("../test_docs_site.py", "tests/test_docs_site.py", "helper.py"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                RUNNER.load_suite([filename])

    def test_failure_summary_includes_test_name_and_traceback(self):
        test = unittest.FunctionTestCase(lambda: None)
        result = SimpleNamespace(
            testsRun=3,
            failures=[(test, "AssertionError: expected value\n")],
            errors=[],
            skipped=[(test, "platform")],
        )
        output = io.StringIO()
        RUNNER.write_result_summary(output, result)
        self.assertIn("3 tests run; 1 failures, 0 errors, 1 skipped", output.getvalue())
        self.assertIn(test.id(), output.getvalue())
        self.assertIn("AssertionError: expected value", output.getvalue())


if __name__ == "__main__":
    unittest.main()
