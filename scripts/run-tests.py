"""Run the test suite with periodic stack dumps for hung CI jobs."""

import faulthandler
import sys
import unittest


def main() -> int:
    faulthandler.enable()
    faulthandler.dump_traceback_later(300, repeat=True)
    try:
        suite = unittest.defaultTestLoader.discover("tests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    sys.exit(main())
