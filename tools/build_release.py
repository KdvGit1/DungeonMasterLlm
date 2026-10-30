"""
Build the Windows release:  python -m tools.build_release

1. app icon
2. PyInstaller one-folder app  → .work/dist/DnDMaster/
3. zip it                      → .work/payload.zip
4. PyInstaller one-file wizard → dist/DnDMaster-Setup.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".work"
DIST = ROOT / "dist"


def run(*args: str) -> None:
    print(">", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    py = sys.executable
    run(py, "installer/make_icon.py")
    run(py, "-m", "PyInstaller", "installer/dndmaster.spec", "--noconfirm",
        "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "build"))
    app = WORK / "dist" / "DnDMaster"
    payload = WORK / "payload.zip"
    payload.unlink(missing_ok=True)
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in app.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(app))
    print(f"payload: {payload.stat().st_size / 1e6:.1f} MB")
    DIST.mkdir(exist_ok=True)
    run(py, "-m", "PyInstaller", "installer/setup.spec", "--noconfirm",
        "--distpath", str(DIST), "--workpath", str(WORK / "build-setup"))
    out = DIST / "DnDMaster-Setup.exe"
    print(f"\nOK → {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
