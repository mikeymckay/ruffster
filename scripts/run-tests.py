"""Run the test suite with periodic stack dumps for hung CI jobs."""

import faulthandler
import os
import sys
import unittest


def main() -> int:
    faulthandler.enable()
    summary_file = None
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        summary_file = open(summary_path, "a", encoding="utf-8")
        summary_file.write("\n### Periodic Python stack traces for stalled tests\n\n```text\n")
    faulthandler.dump_traceback_later(300, repeat=True, file=summary_file or sys.stderr)
    try:
        suite = unittest.defaultTestLoader.discover("tests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        faulthandler.cancel_dump_traceback_later()
        if summary_file:
            summary_file.write("\n```\n")
            summary_file.close()


if __name__ == "__main__":
    sys.exit(main())
