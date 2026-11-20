"""Let the tests import the training scripts in ../train, which are run as plain scripts from that folder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train"))
