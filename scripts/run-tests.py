"""Run the test suite with periodic stack dumps for hung CI jobs."""

import argparse
import faulthandler
import os
import sys
import unittest


def load_suite(files: list[str] | None = None) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    if not files:
        return loader.discover("tests")

    suite = unittest.TestSuite()
    for filename in files:
        invalid_name = (
            not filename.startswith("test_")
            or not filename.endswith(".py")
            or "/" in filename
            or "\\" in filename
        )
        if invalid_name:
            raise ValueError(f"Test shard entries must be test_*.py filenames: {filename}")
        suite.addTests(loader.discover("tests", pattern=filename))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files", nargs="+", metavar="test_file.py",
        help="run only the listed test files (used to split native Windows CI)",
    )
    args = parser.parse_args()
    faulthandler.enable()
    summary_file = None
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        summary_file = open(summary_path, "a", encoding="utf-8")
        summary_file.write("\n### Periodic Python stack traces for stalled tests\n\n```text\n")
    faulthandler.dump_traceback_later(300, repeat=True, file=summary_file or sys.stderr)
    try:
        suite = load_suite(args.files)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        faulthandler.cancel_dump_traceback_later()
        if summary_file:
            summary_file.write("\n```\n")
            summary_file.close()


if __name__ == "__main__":
    sys.exit(main())
