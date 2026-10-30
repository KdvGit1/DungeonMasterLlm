# PyInstaller spec — builds DnDMaster-Setup.exe (single file wizard with the app zipped inside)
ROOT = SPECPATH + "/.."

a = Analysis(
    [ROOT + "/installer/setup_entry.py"],
    pathex=[ROOT],
    datas=[(ROOT + "/.work/payload.zip", "."), (ROOT + "/installer/dndmaster.ico", ".")],
    hiddenimports=[],
    excludes=["fastapi", "starlette", "uvicorn", "pydantic", "httpx", "yaml", "qrcode", "PIL", "pytest",
              "fontTools", "PyInstaller", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="DnDMaster-Setup",
    icon=ROOT + "/installer/dndmaster.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
