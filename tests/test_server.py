import json

import pytest
from fastapi.testclient import TestClient

from dndm.config import AppConfig
from dndm.server.app import create_app
from tests.fakes import FakeLLM


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DNDM_HOME", str(tmp_path))
    app = create_app(AppConfig(port=8765))
    hub = app.state.hub
    hub.llm = FakeLLM()
    hub.session.llm = hub.llm
    hub.session.settings.auto_roll = True
    hub.session.settings.dice_animation_ms = 0
    with TestClient(app) as c:
        c.hub = hub
        yield c


def test_pages_and_catalog(client):
    assert client.get("/table").status_code == 200
    assert client.get("/play").status_code == 200
    assert client.get("/static/shared/dice3d.js").status_code == 200
    cat = client.get("/api/catalog").json()
    assert len(cat["pregens"]) == 8 and "human" in cat["races"] and "wizard" in cat["classes"]
    qr = client.get("/api/qr.svg", params={"url": "http://192.168.1.5:8765/play"})
    assert qr.status_code == 200 and b"<svg" in qr.content


def recv_until(ws, t, limit=50):
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if msg.get("t") == t:
            return msg
    raise AssertionError(f"no {t}")


def test_ws_join_character_start(client):
    with client.websocket_connect("/ws?role=table") as table, client.websocket_connect("/ws?role=player") as phone:
        recv_until(table, "state")
        phone.send_text(json.dumps({"op": "join", "name": "Ayşe"}))
        hello = recv_until(phone, "hello")
        assert hello["player"]["name"] == "Ayşe" and hello["token"]
        phone.send_text(json.dumps({"op": "character", "spec": {"pregen": 1}}))
        st = recv_until(phone, "state")
        while not st["party"]:
            st = recv_until(phone, "state")
        assert st["party"][0]["name"] == "Lira Gölgeayak"
        # reconnecting with the token returns the same player
        with client.websocket_connect("/ws?role=player") as phone2:
            phone2.send_text(json.dumps({"op": "join", "token": hello["token"]}))
            again = recv_until(phone2, "hello")
            assert again["player"]["id"] == hello["player"]["id"]
        table.send_text(json.dumps({"op": "start"}))
        end = recv_until(table, "narration_end", limit=200)
        assert end["kind"] == "opening"
        assert client.hub.session.mode == "exploration"


def test_ws_rejects_ops_before_join(client):
    with client.websocket_connect("/ws?role=player") as phone:
        phone.send_text(json.dumps({"op": "action", "text": "merhaba"}))
        err = recv_until(phone, "error")
        assert "katıl" in err["text"]
