"""
DnDMaster-Setup.exe — a small, self-contained installer (no third-party installer tools).

Pages: welcome → folder & options → install (progress) → finish.
Installs the bundled app folder, creates shortcuts, registers an uninstaller in
"Apps & features" (per-user, no admin), and — only if the user ticks the box and
confirms the Windows UAC prompt — adds a firewall rule so phones on the same
Wi-Fi can connect.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

APP_NAME = "DnD Master"
EXE_NAME = "DnDMaster.exe"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DnDMaster"
FIREWALL_RULE = "DnD Master"
VERSION = "2.0.0"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / ".work"))


def payload_path() -> Path:
    return bundle_dir() / "payload.zip"


def previous_install() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
            return Path(loc) if loc else None
    except OSError:
        return None


def default_dir() -> Path:
    prev = previous_install()
    if prev:
        return prev
    drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    for d in drives:
        if d[0] not in "AC":
            return Path(d) / "DnDMaster"
    return Path(os.environ.get("LOCALAPPDATA", "C:\\")) / "Programs" / "DnDMaster"


def free_gb(path: Path) -> float:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return 0.0


def ps(command: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                   capture_output=True, creationflags=NO_WINDOW, timeout=60)


def make_shortcut(link: Path, target: Path, icon: Path) -> None:
    def q(p):  # PowerShell single-quote escape
        return str(p).replace("'", "''")
    ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(link)}');"
       f"$s.TargetPath='{q(target)}';$s.WorkingDirectory='{q(target.parent)}';"
       f"$s.IconLocation='{q(icon)},0';$s.Description='{APP_NAME}';$s.Save()")


def special_folder(name: str) -> Path:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
                         capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30).stdout.strip()
    return Path(out)


def register_uninstall(app: Path, size_kb: int) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        exe = app / EXE_NAME
        for name, val in [("DisplayName", APP_NAME), ("DisplayVersion", VERSION), ("Publisher", APP_NAME),
                          ("InstallLocation", str(app)), ("DisplayIcon", f"{exe},0"),
                          ("UninstallString", f'"{exe}" --uninstall')]:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in [("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", size_kb)]:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)


def run_elevated(exe: str, args: str) -> bool:
    """ShellExecute 'runas' → Windows shows the UAC prompt to the person installing."""
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 0)
        return rc > 32
    except Exception:
        return False


def add_firewall_rule(app: Path) -> bool:
    exe = app / EXE_NAME
    cmd = (f'/c netsh advfirewall firewall delete rule name="{FIREWALL_RULE}" >nul 2>&1 & '
           f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
           f'program="{exe}" enable=yes profile=private,domain')
    return run_elevated("cmd.exe", cmd)


def remove_firewall_rule() -> bool:
    return run_elevated("cmd.exe", f'/c netsh advfirewall firewall delete rule name="{FIREWALL_RULE}"')


def install(app: Path, *, desktop: bool, startmenu: bool, firewall: bool, progress) -> None:
    app.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload_path()) as z:
        names = z.namelist()
        # replace the program files but never touch downloaded runtime/models or saved games
        internal = app / "_internal"
        if internal.exists():
            shutil.rmtree(internal, ignore_errors=True)
        for i, n in enumerate(names):
            z.extract(n, app)
            if i % 25 == 0:
                progress(0.05 + 0.8 * i / len(names), f"Dosyalar kopyalanıyor… ({i}/{len(names)})")
    size_kb = sum(f.stat().st_size for f in app.rglob("*") if f.is_file() and "runtime" not in f.parts) // 1024
    exe, icon = app / EXE_NAME, app / EXE_NAME
    progress(0.88, "Kısayollar oluşturuluyor…")
    if desktop:
        make_shortcut(special_folder("Desktop") / f"{APP_NAME}.lnk", exe, icon)
    if startmenu:
        make_shortcut(special_folder("Programs") / f"{APP_NAME}.lnk", exe, icon)
    progress(0.93, "Kaldırma bilgisi kaydediliyor…")
    register_uninstall(app, size_kb)
    if firewall:
        progress(0.96, "Güvenlik duvarı izni isteniyor (Windows onay penceresi)…")
        add_firewall_rule(app)
    progress(1.0, "Kurulum tamamlandı.")


def uninstall(app: Path, *, delete_data: bool) -> None:
    """Called from DnDMaster.exe --uninstall (running from inside the install folder)."""
    for folder in ("Desktop", "Programs"):
        try:
            (special_folder(folder) / f"{APP_NAME}.lnk").unlink(missing_ok=True)
        except OSError:
            pass
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except OSError:
        pass
    remove_firewall_rule()
    keep = [] if delete_data else ["runtime", "userdata"]
    # the running exe cannot delete itself: hand off to a detached cmd that waits for us to exit
    targets = [p for p in app.iterdir() if p.name not in keep]
    script = app.parent / "dndmaster_uninstall.cmd"
    lines = ["@echo off", "timeout /t 3 /nobreak >nul"]
    for t in targets:
        lines.append(f'rmdir /s /q "{t}" 2>nul' if t.is_dir() else f'del /f /q "{t}" 2>nul')
    if delete_data:
        lines.append(f'rmdir /s /q "{app}" 2>nul')
    lines.append(f'del /f /q "{script}"')
    script.write_text("\r\n".join(lines), encoding="mbcs" if os.name == "nt" else "utf-8")
    subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))


# ═════════════════════════════════════════════════════════════════
# Wizard UI
# ═════════════════════════════════════════════════════════════════

def run_wizard() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    bg, panel, gold, text, muted = "#15100c", "#1f1813", "#f0cf85", "#ecdfc7", "#a6957b"
    root = tk.Tk()
    root.title(f"{APP_NAME} Kurulumu")
    root.geometry("620x440")
    root.configure(bg=bg)
    root.resizable(False, False)
    try:
        root.iconbitmap(str(bundle_dir() / "dndmaster.ico"))
    except Exception:
        pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("G.Horizontal.TProgressbar", troughcolor="#2a1d12", background="#d9ad55")
    style.configure("TCheckbutton", background=bg, foreground=text, font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", bg)])

    vars_ = {"dir": tk.StringVar(value=str(default_dir())), "desktop": tk.BooleanVar(value=True),
             "startmenu": tk.BooleanVar(value=True), "firewall": tk.BooleanVar(value=True),
             "launch": tk.BooleanVar(value=True)}
    frames: list[tk.Frame] = []

    def page() -> tk.Frame:
        f = tk.Frame(root, bg=bg)
        frames.append(f)
        return f

    def show(i: int) -> None:
        for j, f in enumerate(frames):
            f.place_forget() if j != i else f.place(x=0, y=0, relwidth=1, relheight=1)

    def title(f, t, sub=""):
        tk.Label(f, text=t, font=("Georgia", 22, "bold"), fg=gold, bg=bg).pack(pady=(26, 4))
        if sub:
            tk.Label(f, text=sub, font=("Segoe UI", 10), fg=muted, bg=bg, wraplength=540, justify="center").pack()

    def nav(f, back=None, nxt=None, nxt_text="İleri ›"):
        bar = tk.Frame(f, bg=bg)
        bar.pack(side="bottom", fill="x", pady=16, padx=20)
        tk.Button(bar, text="İptal", command=root.destroy, bg="#2c2218", fg=text, relief="flat", padx=12, pady=5).pack(side="left")
        if nxt:
            tk.Button(bar, text=nxt_text, command=nxt, bg="#d9ad55", fg="#1b1209", relief="flat", padx=16, pady=5,
                      font=("Segoe UI", 10, "bold")).pack(side="right")
        if back:
            tk.Button(bar, text="‹ Geri", command=back, bg="#2c2218", fg=text, relief="flat", padx=12, pady=5).pack(side="right", padx=8)

    # 1 — welcome
    p1 = page()
    title(p1, "DnD Master", "Yapay zekâ anlatıcılı, yerel ağda 1–6 kişilik masa başı macera")
    info = ("• Telefonlar aynı Wi-Fi ağından tarayıcıyla bağlanır, ayrıca uygulama gerekmez.\n"
            "• İlk açılışta yapay zekâ motoru (~1,6 GB) ve anlatıcı model (~7,4 GB) indirilir;\n"
            "   sonrasında oyun tamamen internetsiz çalışır.\n"
            "• Önerilen: NVIDIA ekran kartı (8 GB+, ideal 12 GB), 16 GB RAM, ~12 GB boş disk.\n"
            "• Her şey seçeceğin klasöre kurulur; indirilen modeller de oraya iner.")
    tk.Label(p1, text=info, font=("Segoe UI", 10), fg=text, bg=panel, justify="left", padx=18, pady=14).pack(pady=22, padx=30, fill="x")
    nav(p1, nxt=lambda: show(1))

    # 2 — folder & options
    p2 = page()
    title(p2, "Kurulum Yeri")
    row = tk.Frame(p2, bg=bg)
    row.pack(pady=(14, 4), padx=30, fill="x")
    tk.Entry(row, textvariable=vars_["dir"], font=("Consolas", 11), bg="#0f0b08", fg=text, insertbackground=text,
             relief="flat").pack(side="left", fill="x", expand=True, ipady=6)
    space = tk.Label(p2, text="", font=("Segoe UI", 9), fg=muted, bg=bg)

    def browse():
        d = filedialog.askdirectory(initialdir=vars_["dir"].get())
        if d:
            vars_["dir"].set(str(Path(d) / "DnDMaster") if Path(d).name.lower() != "dndmaster" else d)
            refresh_space()

    def refresh_space(*_):
        g = free_gb(Path(vars_["dir"].get()))
        space.config(text=f"Boş alan: {g:.1f} GB {'— yetersiz olabilir (en az 12 GB önerilir)' if g < 12 else ''}",
                     fg="#f08f86" if g < 12 else muted)

    tk.Button(row, text="Gözat…", command=browse, bg="#2c2218", fg=text, relief="flat", padx=10).pack(side="left", padx=6)
    space.pack(anchor="w", padx=30)
    vars_["dir"].trace_add("write", refresh_space)
    refresh_space()
    opts = tk.Frame(p2, bg=bg)
    opts.pack(pady=18, padx=30, fill="x")
    ttk.Checkbutton(opts, text="Masaüstüne kısayol oluştur", variable=vars_["desktop"]).pack(anchor="w", pady=2)
    ttk.Checkbutton(opts, text="Başlat menüsüne ekle", variable=vars_["startmenu"]).pack(anchor="w", pady=2)
    ttk.Checkbutton(opts, text="Telefonların bağlanabilmesi için Windows Güvenlik Duvarı izni ekle\n"
                               "(yalnızca özel/ev ağları; Windows onay penceresi açılır)",
                    variable=vars_["firewall"]).pack(anchor="w", pady=2)

    def start_install():
        target = Path(vars_["dir"].get().strip().strip('"'))
        if not target.is_absolute():
            messagebox.showerror(APP_NAME, "Lütfen tam bir klasör yolu seç.")
            return
        show(2)
        threading.Thread(target=lambda: do_install(target), daemon=True).start()

    nav(p2, back=lambda: show(0), nxt=start_install, nxt_text="Kur")

    # 3 — progress
    p3 = page()
    title(p3, "Kuruluyor…")
    st = tk.Label(p3, text="Hazırlanıyor…", font=("Segoe UI", 10), fg=text, bg=bg)
    st.pack(pady=(40, 10))
    bar = ttk.Progressbar(p3, style="G.Horizontal.TProgressbar", length=500, maximum=1.0)
    bar.pack()

    # 4 — done
    p4 = page()
    title(p4, "Hazır!", "DnD Master kuruldu. İlk açılışta yapay zekâ dosyaları indirilecek; bu bir kez yapılır.")
    done_lbl = tk.Label(p4, text="", font=("Consolas", 10), fg=muted, bg=bg)
    done_lbl.pack(pady=18)
    ttk.Checkbutton(p4, text="DnD Master'ı şimdi başlat", variable=vars_["launch"]).pack()

    def finish():
        if vars_["launch"].get():
            exe = Path(vars_["dir"].get()) / EXE_NAME
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        root.destroy()

    nav(p4, nxt=finish, nxt_text="Bitir")

    def do_install(target: Path):
        def progress(frac, msg):
            root.after(0, lambda: (bar.config(value=frac), st.config(text=msg)))
        try:
            install(target, desktop=vars_["desktop"].get(), startmenu=vars_["startmenu"].get(),
                    firewall=vars_["firewall"].get(), progress=progress)
            root.after(0, lambda: (done_lbl.config(text=str(target)), show(3)))
        except Exception as exc:
            root.after(0, lambda: messagebox.showerror(APP_NAME, f"Kurulum başarısız: {exc}"))

    show(0)
    root.mainloop()


def run_uninstall_dialog(app: Path) -> None:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno(APP_NAME, "DnD Master kaldırılsın mı?"):
        return
    delete_data = messagebox.askyesno(
        APP_NAME, "İndirilen yapay zekâ modelleri ve kayıtlı oyunlar da silinsin mi?\n\n"
                  "Hayır dersen bu dosyalar klasörde kalır (yeniden kurarsan tekrar indirmen gerekmez).")
    uninstall(app, delete_data=delete_data)
    messagebox.showinfo(APP_NAME, "DnD Master kaldırıldı.")


if __name__ == "__main__":
    run_wizard()
