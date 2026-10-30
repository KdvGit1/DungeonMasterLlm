"""
Filesystem locations. Works both from a source checkout and from a frozen
(PyInstaller) build, where bundled files live under ``sys._MEIPASS``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    return _bundle_root()


def data_dir() -> Path:
    return _bundle_root() / "dndm" / "data"


def web_dir() -> Path:
    return _bundle_root() / "web"


def scenarios_dir() -> Path:
    return _bundle_root() / "scenarios"


def user_dir() -> Path:
    """
    Writable per-install directory (saves, settings, logs).

    Override with ``DNDM_HOME``. Frozen builds default to ``<install>/userdata``
    so nothing lands on C: unless the app itself is installed there.
    """
    env = os.environ.get("DNDM_HOME")
    if env:
        p = Path(env)
    elif getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent / "userdata"
    else:
        p = _bundle_root() / ".runtime" / "userdata"
    p.mkdir(parents=True, exist_ok=True)
    return p
