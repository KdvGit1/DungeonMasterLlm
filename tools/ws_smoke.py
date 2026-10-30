"""End-to-end smoke test against a running server: python -m tools.ws_smoke [port] [scenario]"""

import asyncio
import json
import sys
import time

import websockets


async def main(port: int, scenario: str) -> None:
    uri = f"ws://127.0.0.1:{port}/ws"
    async with websockets.connect(uri + "?role=table") as table, websockets.connect(uri + "?role=player") as phone:
        await phone.send(json.dumps({"op": "join", "name": "Duman"}))
        await phone.send(json.dumps({"op": "character", "spec": {"pregen": 1}}))
        await asyncio.sleep(0.5)
        t0 = time.time()
        await table.send(json.dumps({"op": "start", "scenario_id": scenario}))
        await table.send(json.dumps({"op": "settings", "settings": {"auto_roll": True}}))

        async def wait_for(ws, kind, timeout=240):
            end = time.time() + timeout
            while time.time() < end:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.time()))
                if msg.get("t") == "error":
                    print("ERROR:", msg["text"])
                if msg.get("t") == kind:
                    return msg
            raise TimeoutError(kind)

        opening = await wait_for(table, "narration_end")
        print(f"[açılış {time.time() - t0:.1f}s]\n{opening['text']}\n")
        t1 = time.time()
        await phone.send(json.dumps({"op": "action", "text": "Kalabalığı yarıp örtülü cesedin yanına diz çöküyor ve yaraları inceliyorum."}))
        first = None
        while True:
            msg = json.loads(await asyncio.wait_for(table.recv(), timeout=240))
            if msg.get("t") == "narration_chunk" and first is None:
                first = time.time() - t1
            if msg.get("t") in ("check_result",):
                print("ZAR:", msg["text"])
            if msg.get("t") == "toast":
                print("BİLDİRİM:", msg["text"])
            if msg.get("t") == "narration_end":
                print(f"[tur: ilk kelime {first:.1f}s, toplam {time.time() - t1:.1f}s]\n{msg['text']}")
                break


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8765,
                     sys.argv[2] if len(sys.argv) > 2 else "tuzlukiyida_gumus_ve_kan"))
