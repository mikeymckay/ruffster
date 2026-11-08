"""PyInstaller entry point for the experimental local application core."""
import os
import sys

# The Windows preview is a windowed executable with no attached console.
# Preserve CLI behavior while discarding console-only status/error text.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

from family_activity.__main__ import main

if __name__ == '__main__':
    main()
