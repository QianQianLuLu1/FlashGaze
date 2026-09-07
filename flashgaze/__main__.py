"""支持 `python -m flashgaze` 调用。"""

import sys

from flashgaze.cli.entry import main

if __name__ == "__main__":
    sys.exit(main())
