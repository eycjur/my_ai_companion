"""`python -m ai_companion` のエントリポイント。"""
from __future__ import annotations

import sys

from .controller.menubar import run

if __name__ == "__main__":
    sys.exit(run())
