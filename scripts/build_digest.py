#!/usr/bin/env python3
"""Compatibility entrypoint for the digest builder."""

from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    runpy.run_path(str(ROOT / "tools" / "build-digest.py"), run_name="__main__")
