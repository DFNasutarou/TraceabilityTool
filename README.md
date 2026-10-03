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

### Ubuntu 版の取得から実行まで（GitHub Actions を使う場合）

#### 1. GitHub でビルドする

1. GitHub のリポジトリを開き、上部の **「Actions」** タブを開く。
2. 左の一覧から **「build」** を選ぶ。
3. 一覧の上の帯の右端にある **「Run workflow」** を押し、Branch が `main` のまま緑の **「Run workflow」** を押す。
4. 一覧に実行中の行が出る。5〜10 分ほどで完了する（緑のチェックが成功、赤い × が失敗）。

#### 2. ダウンロードする

1. 完了した行をクリックする。
2. ページ下部の **「Artifacts」** にある **`TraceabilityTool-linux`** をクリックすると、`TraceabilityTool-linux.zip` がダウンロードされる（GitHub へのログインが必要）。
   - Windows でダウンロードした場合は、この zip を**展開せずに**そのまま Ubuntu へコピーする。Windows で展開すると実行権限が失われるため。
   - 成果物の保存期間は 90 日。過ぎたらもう一度ビルドする。

#### 3. Ubuntu で展開する

zip の中に `TraceabilityTool-linux.tar.gz` が入っている（実行権限を保つため tar.gz にまとめている）。端末で次を実行する。

```bash
# unzip が無ければ入れる（初回のみ）
sudo apt install -y unzip

unzip TraceabilityTool-linux.zip
tar -xzf TraceabilityTool-linux.tar.gz
```

`TraceabilityTool-linux/` フォルダができる。このフォルダは好きな場所に移動して構わない（例: `~/apps/TraceabilityTool-linux`）。不要になった `TraceabilityTool-linux.zip` と `TraceabilityTool-linux.tar.gz` は消してよい。

#### 4. 起動する

```bash
cd TraceabilityTool-linux
./TraceabilityTool
```

- ブラウザで `http://127.0.0.1:8765/` が開く。開かない場合（GUI の無い環境など）は、端末に表示された URL を同じ PC のブラウザで開く。
- 終了は端末で `Ctrl + C`。
- `許可がありません`（Permission denied）と出た場合は、一度だけ `chmod +x TraceabilityTool` を実行する。
- `ポート 8765 は…使用中です` と出た場合は、`./TraceabilityTool --port 8800` のように別のポートを指定する。
- データは `~/TraceabilityTool/data` に保存される（ツールのフォルダを差し替えても残る）。

使い方は、フォルダ内の `操作マニュアル.md` を参照。

> Ubuntu 22.04 以降で動作する（GitHub Actions では Ubuntu 22.04 でビルドしている）。それより古い Ubuntu では動かない。

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
