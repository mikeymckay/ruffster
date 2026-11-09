import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
