"""
Desktop launcher (DnDMaster.exe).

First run: downloads the Ollama runtime and the GM model into the install
folder (never into the user profile), with progress bars. Every run: starts
Ollama on a private port, starts the game server, opens the table screen and
shows the address phones should open.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path

import httpx

OLLAMA_RELEASE_API = "https://api.github.com/repos/ollama/ollama/releases/latest"
OLLAMA_ASSET = "ollama-windows-amd64.zip"
OLLAMA_PORT = int(os.environ.get("DNDM_OLLAMA_PORT", "11435"))  # private port: never collides with a system Ollama
GAME_PORT = 8765

MODELS = {
    "recommended": {"name": "hf.co/igorls/gemma-4-12B-it-heretic-GGUF:Q4_K_M", "label": "Önerilen (12 GB+ ekran kartı)",
                    "size_gb": 7.4, "min_vram_gb": 10},
    "light": {"name": "huihui_ai/gemma-4-abliterated:e4b-qat", "label": "Hafif (6–8 GB ekran kartı)",
              "size_gb": 6.3, "min_vram_gb": 6},
}


def install_root() -> Path:
    env = os.environ.get("DNDM_INSTALL_ROOT")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent / ".runtime" / "launcher"


class Runtime:
    def __init__(self, root: Path | None = None):
        self.root = root or install_root()
        self.ollama_dir = Path(os.environ.get("DNDM_OLLAMA_DIR") or self.root / "runtime" / "ollama")
        self.models_dir = Path(os.environ.get("DNDM_MODELS_DIR") or self.root / "runtime" / "models")
        self.home_dir = self.root / "runtime" / "home"
        self.user_dir = self.root / "userdata"
        for d in (self.ollama_dir, self.models_dir, self.home_dir, self.user_dir):
            d.mkdir(parents=True, exist_ok=True)
        os.environ["DNDM_HOME"] = str(self.user_dir)
        self.ollama_proc: subprocess.Popen | None = None
        self.ollama_url = f"http://127.0.0.1:{OLLAMA_PORT}"

    # ── GPU ─────────────────────────────────────────────────────
    @staticmethod
    def vram_gb() -> float | None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return round(int(out.strip().splitlines()[0]) / 1024, 1)
        except Exception:
            return None

    def pick_model(self) -> str:
        cfg_model = self.saved_model()
        if cfg_model:
            return cfg_model
        vram = self.vram_gb()
        key = "recommended" if (vram is None or vram >= MODELS["recommended"]["min_vram_gb"]) else "light"
        return MODELS[key]["name"]

    def saved_model(self) -> str | None:
        p = self.user_dir / "config.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("model")
            except Exception:
                return None
        return None

    # ── Ollama runtime ─────────────────────────────────────────
    def ollama_exe(self) -> Path:
        return self.ollama_dir / "ollama.exe"

    def has_ollama(self) -> bool:
        return self.ollama_exe().exists()

    def download_ollama(self, progress) -> None:
        with httpx.Client(follow_redirects=True, timeout=60) as c:
            rel = c.get(OLLAMA_RELEASE_API, headers={"Accept": "application/vnd.github+json"}).json()
            asset = next(a for a in rel["assets"] if a["name"] == OLLAMA_ASSET)
            url, total = asset["browser_download_url"], asset["size"]
            tmp = self.root / "runtime" / "ollama-download.zip"
            done = 0
            with c.stream("GET", url) as r, open(tmp, "wb") as f:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    progress(done / total, f"Yapay zekâ motoru indiriliyor… {done >> 20} / {total >> 20} MB")
        progress(1.0, "Yapay zekâ motoru açılıyor…")
        with zipfile.ZipFile(tmp) as z:
            z.extractall(self.ollama_dir)
        tmp.unlink(missing_ok=True)

    def ollama_alive(self) -> bool:
        try:
            return httpx.get(f"{self.ollama_url}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start_ollama(self) -> None:
        if self.ollama_alive():
            return
        env = dict(os.environ)
        env.update({
            "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}",
            "OLLAMA_MODELS": str(self.models_dir),
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_KV_CACHE_TYPE": "q8_0",
            "OLLAMA_KEEP_ALIVE": "60m",
            "USERPROFILE": str(self.home_dir),   # keeps Ollama's key files inside the install folder
            "HOME": str(self.home_dir),
        })
        log = open(self.root / "runtime" / "ollama.log", "ab")
        self.ollama_proc = subprocess.Popen(
            [str(self.ollama_exe()), "serve"], env=env, stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(60):
            if self.ollama_alive():
                return
            time.sleep(0.5)
        raise RuntimeError("Yapay zekâ motoru başlatılamadı (ollama.log dosyasına bakın).")

    def stop_ollama(self) -> None:
        if self.ollama_proc and self.ollama_proc.poll() is None:
            self.ollama_proc.terminate()
            try:
                self.ollama_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.ollama_proc.kill()

    def has_model(self, model: str) -> bool:
        try:
            tags = httpx.get(f"{self.ollama_url}/api/tags", timeout=10).json().get("models", [])
        except httpx.HTTPError:
            return False
        return any(t["name"] == model or t.get("model") == model for t in tags)

    def pull_model(self, model: str, progress) -> None:
        with httpx.Client(timeout=None) as c:
            with c.stream("POST", f"{self.ollama_url}/api/pull", json={"model": model, "stream": True}) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    total, done = msg.get("total"), msg.get("completed")
                    if total and done:
                        progress(done / total, f"Anlatıcı model indiriliyor… {done / 1e9:.1f} / {total / 1e9:.1f} GB")
                    else:
                        progress(None, f"Model hazırlanıyor: {msg.get('status', '')}")

    def warm_up(self, model: str) -> None:
        try:
            httpx.post(f"{self.ollama_url}/api/chat", timeout=300, json={
                "model": model, "messages": [{"role": "user", "content": "Merhaba"}], "stream": False,
                "think": False, "options": {"num_predict": 1, "num_ctx": 8192}, "keep_alive": "60m"})
        except httpx.HTTPError:
            pass


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class ServerThread(threading.Thread):
    def __init__(self, ollama_url: str, model: str, port: int):
        super().__init__(daemon=True)
        import uvicorn
        from dndm.config import load_config, save_config
        from dndm.server.app import create_app
        cfg = load_config()
        cfg.ollama_url, cfg.model, cfg.port, cfg.host = ollama_url, model, port, "0.0.0.0"
        save_config(cfg)
        self.server = uvicorn.Server(uvicorn.Config(create_app(cfg), host=cfg.host, port=port, log_level="warning",
                                                    ws_ping_interval=20))

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# ═════════════════════════════════════════════════════════════════
# Window
# ═════════════════════════════════════════════════════════════════

def run_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    rt = Runtime()
    ui_q: queue.Queue = queue.Queue()
    state = {"server": None, "url": None}

    root = tk.Tk()
    root.title("DnD Master")
    root.geometry("560x400")
    root.configure(bg="#15100c")
    root.resizable(False, False)
    try:
        ico = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "installer" / "dndmaster.ico"
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Gold.Horizontal.TProgressbar", troughcolor="#2a1d12", background="#d9ad55", bordercolor="#3b2d20",
                    lightcolor="#f0cf85", darkcolor="#a9792f")
    gold, text, muted, bg = "#f0cf85", "#ecdfc7", "#a6957b", "#15100c"
    tk.Label(root, text="DnD Master", font=("Georgia", 28, "bold"), fg=gold, bg=bg).pack(pady=(22, 0))
    tk.Label(root, text="Yapay zekâ anlatıcılı masa başı macera", font=("Segoe UI", 10), fg=muted, bg=bg).pack()
    status = tk.Label(root, text="Hazırlanıyor…", font=("Segoe UI", 11), fg=text, bg=bg, wraplength=500)
    status.pack(pady=(26, 8))
    bar = ttk.Progressbar(root, style="Gold.Horizontal.TProgressbar", length=480, mode="determinate", maximum=1.0)
    bar.pack()
    url_lbl = tk.Label(root, text="", font=("Consolas", 15, "bold"), fg=gold, bg=bg)
    url_lbl.pack(pady=(22, 2))
    hint = tk.Label(root, text="", font=("Segoe UI", 9), fg=muted, bg=bg)
    hint.pack()
    btns = tk.Frame(root, bg=bg)
    btns.pack(pady=18)
    open_btn = tk.Button(btns, text="Masayı Aç", state="disabled", font=("Segoe UI", 11, "bold"), bg="#d9ad55",
                         fg="#1b1209", activebackground="#f0cf85", relief="flat", padx=18, pady=6,
                         command=lambda: webbrowser.open(f"http://localhost:{GAME_PORT}/table"))
    open_btn.pack(side="left", padx=6)
    tk.Button(btns, text="Klasörü Aç", font=("Segoe UI", 10), bg="#2c2218", fg=text, relief="flat", padx=12, pady=6,
              command=lambda: os.startfile(str(rt.root))).pack(side="left", padx=6)
    tk.Button(btns, text="Kapat", font=("Segoe UI", 10), bg="#5b1d1a", fg=text, relief="flat", padx=12, pady=6,
              command=lambda: on_close()).pack(side="left", padx=6)

    def progress(frac, msg):
        ui_q.put(("progress", frac, msg))

    def worker():
        try:
            if not port_free(GAME_PORT):
                ui_q.put(("error", f"{GAME_PORT} numaralı port kullanımda. DnD Master zaten açık olabilir."))
                return
            if not rt.has_ollama():
                rt.download_ollama(progress)
            progress(None, "Yapay zekâ motoru başlatılıyor…")
            rt.start_ollama()
            model = rt.pick_model()
            if not rt.has_model(model):
                rt.pull_model(model, progress)
            progress(None, "Anlatıcı uyandırılıyor (ilk açılış biraz sürebilir)…")
            rt.warm_up(model)
            progress(None, "Oyun sunucusu başlatılıyor…")
            srv = ServerThread(rt.ollama_url, model, GAME_PORT)
            srv.start()
            for _ in range(60):
                if not port_free(GAME_PORT):
                    break
                time.sleep(0.25)
            state["server"] = srv
            ui_q.put(("ready", f"http://{lan_ip()}:{GAME_PORT}/play"))
        except Exception as exc:  # pragma: no cover - surfaced to the user
            ui_q.put(("error", f"Hata: {exc}"))

    def pump():
        try:
            while True:
                item = ui_q.get_nowait()
                if item[0] == "progress":
                    _, frac, msg = item
                    status.config(text=msg)
                    if frac is None:
                        bar.config(mode="indeterminate")
                        bar.start(12)
                    else:
                        bar.stop()
                        bar.config(mode="determinate", value=frac)
                elif item[0] == "ready":
                    bar.stop()
                    bar.config(mode="determinate", value=1.0)
                    status.config(text="Hazır! Masa ekranı tarayıcıda açılıyor.")
                    url_lbl.config(text=item[1].replace("http://", ""))
                    hint.config(text="Aynı Wi-Fi'deki telefonlardan bu adrese girin (ya da masadaki QR kodu okutun).")
                    open_btn.config(state="normal")
                    webbrowser.open(f"http://localhost:{GAME_PORT}/table")
                elif item[0] == "error":
                    bar.stop()
                    status.config(text=item[1], fg="#f08f86")
        except queue.Empty:
            pass
        root.after(150, pump)

    def on_close():
        if state["server"] is not None and not messagebox.askyesno("DnD Master", "Oyunu kapatmak istiyor musun? "
                                                                                 "(Oyun otomatik kaydedildi.)"):
            return
        status.config(text="Kapatılıyor…")
        root.update()
        if state["server"] is not None:
            state["server"].stop()
        rt.stop_ollama()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    threading.Thread(target=worker, daemon=True).start()
    root.after(150, pump)
    root.mainloop()


def main() -> None:
    if "--uninstall" in sys.argv:
        from dndm.setup_wizard import run_uninstall_dialog
        run_uninstall_dialog(install_root())
        return
    if "--server-only" in sys.argv:
        rt = Runtime()
        rt.start_ollama()
        srv = ServerThread(rt.ollama_url, rt.pick_model(), GAME_PORT)
        srv.run()
        return
    run_gui()


if __name__ == "__main__":
    main()
