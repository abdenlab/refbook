"""Make the pipeline scripts importable, so their pure parts can be tested."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
