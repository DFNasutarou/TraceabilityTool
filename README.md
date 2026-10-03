# トレーサビリティツール

表形式の仕様書・設計書（CSV / TSV / Excel）を取り込み、文書間の項目を相互に追跡するためのローカルツールです。
データはすべて PC 内で処理し、外部への通信は行いません。

- 要件定義書: [docs/01_requirements.md](docs/01_requirements.md)
- 詳細設計書: [docs/02_design.md](docs/02_design.md)

## 必要なもの

- Python 3.11 以上

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

開発（テスト）用の依存も入れる場合:

```bash
.venv\Scripts\python -m pip install -e ".[dev]"
```

## 起動

```bash
.venv\Scripts\python -m tracetool
```

- ブラウザで `http://127.0.0.1:8765/` が開きます（`127.0.0.1` でのみ待ち受けるため、他の PC からは接続できません）。
- 終了はコンソールで `Ctrl+C`。

| オプション | 説明 | 既定値 |
|---|---|---|
| `--data-dir PATH` | データフォルダ | `%USERPROFILE%\TraceabilityTool\data` |
| `--port N` | ポート番号 | `8765` |
| `--no-browser` | ブラウザを自動で開かない | |

データフォルダには `tracetool.db`（SQLite）と `logs/` が作られます。バックアップはフォルダごとコピーしてください（ツールを終了してからコピーすること）。
ログには項目の値を書き込みません。

## 使い方の流れ

1. **文書を追加**: 文書一覧の「文書を追加」から、文書名とカラム定義（任意）を登録する。
2. **取り込み**: ファイルを選択 → 文字コード・ヘッダ行・シートを指定 → 列の対応付けと型を確認して「検証」→「取り込む」。
   取り込むたびに新しい版になります。
3. **トレース関係**: 文書一覧の下部で「上位文書 → 下位文書」を登録する。
4. **リンク**:
   - 参照 ID 列（カラム定義で「参照先」を指定した文字列列）から自動で作られます。
   - 項目一覧で項目をクリックすると右側に詳細が表示され、リンクの追加・削除・確認済みができます。
5. **トレース状況**: 網羅率、上位なし・下位なし、リンク切れ、要確認を確認し、Excel / CSV に出力する。
6. **版・差分**: 2 つの版を比較し、追加・削除・変更された項目を確認・出力する。

## テスト

```bash
.venv\Scripts\python -m pytest
```

## 同梱しているサードパーティ製ファイル

| ファイル | 内容 | 取得元 | SHA-256 |
|---|---|---|---|
| `tracetool/static/vendor/vue.global.prod.js` | Vue.js 3.5.43（MIT License、`vue.LICENSE` を同梱） | npm 公式パッケージ `vue@3.5.43`（`https://registry.npmjs.org/vue/-/vue-3.5.43.tgz`。取得時に npm のパッケージ整合性ハッシュ sha512 の一致を確認済み）の `dist/vue.global.prod.js` | `b72394052eef1eeda1752db3758ce1be6f88016903f22e5241cc732ea307478e` |

実行時に CDN などから読み込むことはありません。
