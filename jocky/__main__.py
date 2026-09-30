"""Allow `python -m jocky` alongside the `jocky` console script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
