# PyInstaller spec — builds dist/DnDMaster/DnDMaster.exe (one-folder, windowed)
# run: pyinstaller installer/dndmaster.spec --noconfirm --distpath .work/dist --workpath .work/build
from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH + "/.."

datas = [
    (ROOT + "/web", "web"),
    (ROOT + "/scenarios", "scenarios"),
    (ROOT + "/dndm/data", "dndm/data"),
    (ROOT + "/installer/dndmaster.ico", "installer"),
    (ROOT + "/LICENSE", "."),
    (ROOT + "/docs/LICENSES.md", "docs"),
]
hidden = (collect_submodules("uvicorn") + collect_submodules("websockets") + collect_submodules("qrcode")
          + ["httptools", "h11", "anyio._backends._asyncio"])

a = Analysis(
    [ROOT + "/installer/launcher_entry.py"],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "PIL", "fontTools", "PyInstaller", "pydoc", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="DnDMaster",
    icon=ROOT + "/installer/dndmaster.ico",
    console=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DnDMaster")
