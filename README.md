# トレーサビリティツール（開発用リポジトリ）

表形式の仕様書・設計書（CSV / TSV / Excel）を取り込み、文書間の項目を相互に追跡するためのローカルツールです。
データはすべて PC 内で処理し、外部への通信は行いません。

このリポジトリはツールの**開発用**です。利用者に渡すのは、ビルドで作る**配布フォルダ**だけです（後述）。

## リポジトリの構成

| パス | 内容 | 配布フォルダに入るか |
|---|---|---|
| `tracetool/` | ツール本体（Python パッケージと画面） | ○（実行ファイルに組み込まれる） |
| `packaging/build.py` | 配布フォルダを作るスクリプト | × |
| `packaging/entry.py` | 実行ファイルのエントリポイント | ○（実行ファイルに組み込まれる） |
| `packaging/user_files/` | 利用者向けの資料（操作マニュアル）。中身がそのまま配布フォルダにコピーされる | ○ |
| `docs/` | 要件定義書・詳細設計書 | × |
| `tests/` | テスト | × |
| `.github/workflows/build.yml` | Windows 版・Ubuntu 版の配布フォルダを作る GitHub Actions | × |

- 要件定義書: [docs/01_requirements.md](docs/01_requirements.md)
- 詳細設計書: [docs/02_design.md](docs/02_design.md)
- 操作マニュアル（利用者向け）: [packaging/user_files/操作マニュアル.md](packaging/user_files/操作マニュアル.md)

## 配布フォルダ

```
TraceabilityTool-windows/            TraceabilityTool-linux/
  TraceabilityTool.exe                 TraceabilityTool
  _internal/   … 実行に必要なファイル     _internal/
  操作マニュアル.md                       操作マニュアル.md
```

- フォルダをコピーするだけで使えます。利用者の PC に Python は不要です。
- PyInstaller は実行した OS 向けの実行ファイルしか作れないため、**Windows 版は Windows で、Ubuntu 版は Ubuntu でビルド**します。
- Ubuntu 版は、ビルドした Ubuntu と同じかそれより新しい Ubuntu で動きます（GitHub Actions では Ubuntu 22.04 でビルドしています）。

### ビルド手順

開発環境を用意したうえで（次節）、ビルドしたい OS で次を実行します。

```bash
python packaging/build.py
```

`dist/TraceabilityTool-windows/` または `dist/TraceabilityTool-linux/` ができます。`build/` と `dist/` は git の管理外です。

GitHub Actions の「build」ワークフローを手動で実行する（または `v*` タグを push する）と、両 OS 版が成果物（Artifacts）として作られます。

## 開発環境

Python 3.11 以上が必要です。

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

（Ubuntu では `.venv/bin/python`）

### 開発中の起動

```bash
.venv\Scripts\python -m tracetool --data-dir ./data
```

- ブラウザで `http://127.0.0.1:8765/` が開きます。`127.0.0.1` でのみ待ち受け、Host / Origin ヘッダも検査します（DNS リバインディング・CSRF 対策）。
- `--data-dir` を省略すると `%USERPROFILE%\TraceabilityTool\data`（Ubuntu は `~/TraceabilityTool/data`）を使います。`data/` は git の管理外です。

### テスト

```bash
.venv\Scripts\python -m pytest
```

テストデータはテスト内で生成します。実際の仕様書をリポジトリに置かないでください（`.gitignore` で `*.xlsx` `*.csv` などを除外しています）。

## 同梱しているサードパーティ製ファイル

| ファイル | 内容 | 取得元 | SHA-256 |
|---|---|---|---|
| `tracetool/static/vendor/vue.global.prod.js` | Vue.js 3.5.43（MIT License、`vue.LICENSE` を同梱） | npm 公式パッケージ `vue@3.5.43`（`https://registry.npmjs.org/vue/-/vue-3.5.43.tgz`。取得時に npm のパッケージ整合性ハッシュ sha512 の一致を確認済み）の `dist/vue.global.prod.js` | `b72394052eef1eeda1752db3758ce1be6f88016903f22e5241cc732ea307478e` |

実行時に CDN などから読み込むことはありません。
