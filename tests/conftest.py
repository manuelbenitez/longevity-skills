"""Shared pytest config: add repo root to sys.path so tests can import scripts.lib."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
