"""起動: python -m tracetool [--data-dir PATH] [--port 8765] [--no-browser]"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

HOST = "127.0.0.1"  # 外部から接続させない（N-03）


def default_data_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "TraceabilityTool" / "data"


def setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "tracetool.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("tracetool")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def main() -> None:
    parser = argparse.ArgumentParser(prog="tracetool", description="トレーサビリティツール")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="データフォルダ")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    args = parser.parse_args()

    import uvicorn

    from .app import create_app
    from .db import Database

    data_dir: Path = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(data_dir)
    db = Database(data_dir / "tracetool.db")
    app = create_app(db)

    url = f"http://{HOST}:{args.port}/"
    print(f"データフォルダ: {data_dir}")
    print(f"起動しました: {url}  （終了は Ctrl+C）")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=HOST, port=args.port, log_level="warning")
    finally:
        db.close()


if __name__ == "__main__":
    main()
