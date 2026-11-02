#!/usr/bin/env python3
"""Initialize one isolated local instance; no vendor account configuration."""

import sys
from local_runtime import main

if __name__ == "__main__":
    sys.argv.insert(1, "setup")
    raise SystemExit(main())
