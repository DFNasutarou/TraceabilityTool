"""配布フォルダを作る。

    python packaging/build.py

実行した OS 向けの配布フォルダ dist/TraceabilityTool-<windows|linux>/ を作る。
PyInstaller は実行した OS 向けの実行ファイルしか作れないため、Windows 版は Windows で、
Ubuntu 版は Ubuntu で実行すること。

配布フォルダに入れるのは、ツールの実行に必要なものと利用者向けの操作マニュアルだけ。
設計書・テスト・ソースコードは入れない。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
APP_NAME = "TraceabilityTool"

# 利用者向けに配布フォルダへ入れるファイル（packaging/user_files/ 以下をそのままコピーする）
USER_FILES = PACKAGING / "user_files"


def platform_tag() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"未対応の OS です: {sys.platform}")


def main() -> None:
    import PyInstaller.__main__

    tag = platform_tag()
    work = ROOT / "build" / "pyinstaller" / tag
    staging = ROOT / "build" / "staging" / tag
    out = ROOT / "dist" / f"{APP_NAME}-{tag}"
    static = ROOT / "tracetool" / "static"

    for d in (work, staging, out):
        shutil.rmtree(d, ignore_errors=True)

    PyInstaller.__main__.run(
        [
            str(PACKAGING / "entry.py"),
            "--name", APP_NAME,
            "--onedir",
            "--console",  # 起動中の URL と終了方法（Ctrl+C）を表示するため、コンソールを出す
            "--noconfirm",
            "--clean",
            "--distpath", str(staging),
            "--workpath", str(work),
            "--specpath", str(work),
            "--paths", str(ROOT),
            "--add-data", f"{static}{os.pathsep}tracetool/static",
            # uvicorn は実行時にプロトコル実装を動的に読み込むため、明示的に含める
            "--collect-submodules", "uvicorn",
            # 実行に不要なモジュールを含めない
            "--exclude-module", "tkinter",
            "--exclude-module", "pytest",
            "--exclude-module", "_pytest",
            "--exclude-module", "httpx",
        ]
    )

    shutil.copytree(staging / APP_NAME, out)
    for f in USER_FILES.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    shutil.rmtree(ROOT / "build" / "staging", ignore_errors=True)
    print(f"\n配布フォルダを作成しました: {out}")


if __name__ == "__main__":
    main()
