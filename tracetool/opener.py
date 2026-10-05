"""データフォルダを OS のファイル管理画面（エクスプローラーなど）で開く。

ツールは 127.0.0.1 だけで待ち受けるため、画面を操作している PC = サーバの PC であり、サーバ側で開けばよい。
開くフォルダは起動時に決まったデータフォルダだけで、画面から渡された値は使わない。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .errors import AppError


def open_folder(path: Path) -> None:
    if not path.is_dir():
        raise AppError(f"フォルダがありません: {path}")
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows のみ
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, FileNotFoundError) as exc:
        raise AppError(
            f"フォルダを開けませんでした（{type(exc).__name__}）。ファイル管理画面で次のフォルダを開いてください: {path}"
        ) from exc
