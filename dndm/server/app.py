"""
HTTP + WebSocket server.

One game table per server process. The PC opens /table (big screen, dice,
narration); phones on the same Wi-Fi open http://<pc-ip>:<port>/play (or scan
the QR code shown on the table). Every message from the GameSession is fanned
out to the right sockets.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from dndm import __version__
from dndm.config import AppConfig, load_config, save_config
from dndm.game.combat.engine import CombatError
from dndm.game.creation import PREGENS, STANDARD_ARRAY, make_pregen
from dndm.game.inventory import InventoryError
from dndm.game.session import GameSession, list_saves
from dndm.llm.client import OllamaClient
from dndm.paths import web_dir
from dndm.rules import data
from dndm.rules.core import ABILITY_TR, SKILL_TR
from dndm.world.scenario import list_scenarios

log = logging.getLogger("dndm.server")


def lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outbound interface
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254"):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


class Hub:
    """Tracks sockets and the single active session."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.llm = OllamaClient(cfg.model, cfg.ollama_url, num_ctx=cfg.num_ctx)
        self.session: GameSession = GameSession(self.llm, emit=self.emit)
        self.sockets: dict[WebSocket, dict] = {}   # ws -> {"role": "table"|"player", "player_id": str|None}
        self.lock = asyncio.Lock()

    async def emit(self, msg: dict, to: list[str] | None) -> None:
        data_ = json.dumps(msg, ensure_ascii=False, default=str)
        dead = []
        for ws, meta in list(self.sockets.items()):
            if to is not None:
                if meta["role"] == "table":
                    if "table" not in to:
                        continue
                elif meta.get("player_id") not in to:
                    continue
            try:
                await ws.send_text(data_)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets.pop(ws, None)

    def new_session(self) -> None:
        self.session = GameSession(self.llm, emit=self.emit)

    def load_session(self, sid: str) -> None:
        self.session = GameSession.load(self.llm, sid, emit=self.emit)

    def set_model(self, model: str) -> None:
        self.cfg.model = model
        self.llm.model = model
        save_config(self.cfg)


def create_app(cfg: AppConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="DnD Master", version=__version__)
    hub = Hub(cfg)
    app.state.hub = hub
    web = web_dir()
    app.mount("/static", StaticFiles(directory=str(web)), name="static")

    @app.middleware("http")
    async def revalidate_static(request: Request, call_next):
        # phones keep tabs open for hours; make them revalidate app code (cheap 304s on LAN)
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") and not path.startswith("/static/vendor/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # ── pages ────────────────────────────────────────────────────
    @app.get("/")
    async def root(request: Request):
        host = request.client.host if request.client else ""
        return RedirectResponse("/table" if host in ("127.0.0.1", "::1", "localhost") else "/play")

    @app.get("/table")
    async def table_page():
        return FileResponse(web / "table" / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/play")
    async def play_page():
        return FileResponse(web / "player" / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(web / "shared" / "favicon.svg", media_type="image/svg+xml")

    # ── info ─────────────────────────────────────────────────────
    @app.get("/api/info")
    async def info():
        ips = lan_ips()
        port = cfg.port
        urls = [f"http://{ip}:{port}/play" for ip in ips]
        llm_ok = await hub.llm.health()
        return {"version": __version__, "ips": ips, "port": port, "join_urls": urls, "model": cfg.model,
                "llm_ok": llm_ok, "session": hub.session.id, "mode": hub.session.mode}

    @app.get("/api/qr.svg")
    async def qr(url: str):
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.get("/api/catalog")
    async def catalog():
        pregens = []
        for i, spec in enumerate(PREGENS):
            ch = make_pregen(i)
            pregens.append({"index": i, "name": ch.name, "race": ch.race_name, "class": ch.class_name,
                            "portrait": ch.portrait, "appearance": ch.appearance, "personality": ch.personality,
                            "backstory": ch.backstory, "hp": ch.max_hp, "ac": ch.armor_class(),
                            "abilities": ch.abilities})
        return {
            "races": {k: {"name": v.name, "description": v.description, "bonus": v.ability_bonus,
                          "speed": v.speed, "darkvision": v.darkvision, "traits": v.traits}
                      for k, v in data.races().items()},
            "classes": {k: {"name": v.name, "description": v.description, "hit_die": v.hit_die,
                            "primary": v.primary, "skills": v.skill_choices, "saves": v.saves}
                        for k, v in data.classes().items()},
            "abilities": ABILITY_TR, "skills": SKILL_TR, "standard_array": STANDARD_ARRAY,
            "pregens": pregens, "scenarios": list_scenarios(),
        }

    @app.get("/api/saves")
    async def saves():
        return {"saves": list_saves()}

    @app.get("/api/config")
    async def get_config():
        models: list[str] = []
        try:
            r = await hub.llm._http().get("/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return {"model": cfg.model, "models": models, "ollama_url": cfg.ollama_url, "port": cfg.port}

    @app.post("/api/config")
    async def set_config(body: dict):
        if body.get("model"):
            hub.set_model(str(body["model"]))
        return {"ok": True, "model": cfg.model}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/{page}")
    async def case_insensitive_pages(page: str):
        low = page.lower()
        if low in ("play", "table") and page != low:
            return RedirectResponse(f"/{low}")
        if low in ("oyna", "katil", "katıl", "join"):
            return RedirectResponse("/play")
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # ── websocket ────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        role = ws.query_params.get("role", "player")
        meta: dict[str, Any] = {"role": "table" if role == "table" else "player", "player_id": None}
        hub.sockets[ws] = meta
        try:
            if meta["role"] == "table":
                await ws.send_text(json.dumps(hub.session.public_state("table"), ensure_ascii=False, default=str))
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                try:
                    await handle(hub, ws, meta, msg)
                except (ValueError, CombatError, InventoryError, KeyError) as exc:
                    await ws.send_text(json.dumps({"t": "error", "text": _err_text(exc)}, ensure_ascii=False))
                except Exception as exc:  # pragma: no cover - keep the socket alive
                    log.exception("ws handler error")
                    await ws.send_text(json.dumps({"t": "error", "text": "Beklenmeyen bir hata oldu."},
                                                  ensure_ascii=False))
        except WebSocketDisconnect:
            pass
        finally:
            hub.sockets.pop(ws, None)
            pid = meta.get("player_id")
            if pid and pid in hub.session.players:
                still = any(m.get("player_id") == pid for m in hub.sockets.values())
                if not still:
                    hub.session.players[pid].connected = False
                    await hub.session.broadcast_state()

    return app


def _err_text(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "Bulunamadı."
    return str(exc)


async def handle(hub: Hub, ws: WebSocket, meta: dict, msg: dict) -> None:
    op = msg.get("op")
    s = hub.session
    is_table = meta["role"] == "table"
    pid = meta.get("player_id")

    async def reply(obj: dict) -> None:
        await ws.send_text(json.dumps(obj, ensure_ascii=False, default=str))

    if op == "ping":
        await reply({"t": "pong"})
        return

    # ── player identity ──────────────────────────────────────────
    if op == "join":
        p = s.join(str(msg.get("name", "")), msg.get("token"))
        p.connected = True
        meta["player_id"] = p.id
        await reply({"t": "hello", "player": p.public(), "token": p.token})
        await s.broadcast_state()
        return

    # ── table / host controls ────────────────────────────────────
    host_ok = is_table or (pid and s.players.get(pid) and s.players[pid].is_host)
    if op == "new_session" and is_table:
        hub.new_session()
        await hub.emit({"t": "reset"}, None)
        await hub.session.broadcast_state()
        return
    if op == "load_session" and is_table:
        hub.load_session(str(msg["id"]))
        await hub.emit({"t": "reset"}, None)
        await hub.session.broadcast_state()
        return
    if op == "start" and host_ok:
        asyncio.create_task(_safe(s.start(scenario_id=msg.get("scenario_id") or None,
                                          premise=str(msg.get("premise", ""))[:1500]), hub))
        return
    if op == "settings" and host_ok:
        new = {**s.settings.model_dump(), **(msg.get("settings") or {})}
        s.settings = type(s.settings).model_validate(new)
        await s.broadcast_state()
        return
    if op == "force_round" and host_ok:
        await s.force_round()
        return
    if op == "save" and is_table:
        path = s.save()
        await reply({"t": "toast", "text": "Oyun kaydedildi." if path else "Kayıt başarısız!", "kind": "info"})
        return
    if op == "kick" and is_table:
        s.leave(str(msg["player_id"]))
        await s.broadcast_state()
        return
    if op == "set_model" and is_table:
        hub.set_model(str(msg["model"]))
        await reply({"t": "toast", "text": f"Model: {msg['model']}", "kind": "info"})
        return

    # ── player ops ───────────────────────────────────────────────
    if pid is None or pid not in s.players:
        await reply({"t": "error", "text": "Önce masaya katıl."})
        return
    if op == "character":
        ch = s.set_character(pid, msg.get("spec") or {})
        await reply({"t": "toast", "text": f"{ch.name} hazır!", "kind": "info"})
        await s.broadcast_state()
    elif op == "ready":
        s.players[pid].ready = bool(msg.get("value", True))
        await s.broadcast_state()
    elif op == "action":
        await s.submit_action(pid, str(msg.get("text", "")), private=bool(msg.get("private")))
    elif op == "withdraw":
        await s.withdraw_action(pid)
    elif op == "roll":
        s.answer_roll(pid, str(msg.get("id")))
    elif op == "combat":
        asyncio.create_task(_safe_reply(s.combat_command(pid, msg.get("cmd") or {}), ws))
    elif op == "inventory":
        text = await s.inventory_command(pid, msg.get("cmd") or {})
        await reply({"t": "toast", "text": text, "kind": "item"})
    else:
        await reply({"t": "error", "text": f"Bilinmeyen işlem: {op}"})


async def _safe(coro, hub: Hub) -> None:
    try:
        await coro
    except (ValueError, CombatError, InventoryError) as exc:
        await hub.emit({"t": "error", "text": str(exc)}, None)
    except Exception:
        log.exception("background op failed")
        await hub.emit({"t": "error", "text": "Beklenmeyen bir hata oldu."}, None)


async def _safe_reply(coro, ws: WebSocket) -> None:
    try:
        await coro
    except (ValueError, CombatError, InventoryError, KeyError) as exc:
        try:
            await ws.send_text(json.dumps({"t": "error", "text": _err_text(exc)}, ensure_ascii=False))
        except Exception:
            pass
    except Exception:
        log.exception("combat command failed")
