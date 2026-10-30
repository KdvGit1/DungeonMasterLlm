"""Run the server: python -m dndm [--port 8765]"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from dndm.config import load_config
from dndm.server.app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="DnD Master server")
    ap.add_argument("--port", type=int)
    ap.add_argument("--host")
    ap.add_argument("--model")
    args = ap.parse_args()
    cfg = load_config()
    if args.port:
        cfg.port = args.port
    if args.host:
        cfg.host = args.host
    if args.model:
        cfg.model = args.model
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info", ws_ping_interval=20)


if __name__ == "__main__":
    main()
