# トレーサビリティツール 詳細設計書

- 版: 0.3（レビュー指摘の反映、配布方式の追加）
- 作成日: 2026-10-03
- 対応する要件定義書: `01_requirements.md` 版 0.2

## 1. 技術構成

| 層 | 採用技術 | 理由 |
|---|---|---|
| 言語 | Python 3.11 以上 | |
| Web サーバ | FastAPI + uvicorn | 型付き API、ファイルアップロードの扱いが容易 |
| DB | SQLite（標準ライブラリ `sqlite3`） | 単一ファイル、インストール不要、トランザクションあり |
| Excel 読み書き | openpyxl | .xlsx の結合セル情報を取得できる |
| 文字コード判定 | 自前（UTF-8 BOM → UTF-8 → CP932 の順に試す） | 依存を増やさない |
| 画面 | Vue 3（`vue.global.prod.js` をリポジトリに同梱）＋素の ES Modules | ビルド不要・CDN 不使用 |
| テスト | pytest | |
| 配布 | PyInstaller（onedir） | 利用者の PC に Python 不要。フォルダのコピーだけで使える |

### 1.1 起動

```
python -m tracetool [--data-dir PATH] [--port 8765] [--no-browser]
```

- `127.0.0.1` にのみバインドする（N-03）。
- 起動後に既定ブラウザで `http://127.0.0.1:<port>/` を開く（N-06）。
- データフォルダの既定値は `%USERPROFILE%\TraceabilityTool\data`（Ubuntu は `~/TraceabilityTool/data`）。リポジトリ配下にも配布フォルダ内にも置かない（機密データを誤ってコミットしないため。また配布フォルダを差し替えて更新してもデータが残るように）。
- 起動前にポートが空いているか確認し、使用中なら理由を表示して終了する（exe をダブルクリックした場合は Enter を押すまで待ち、メッセージを読めるようにする）。

### 1.2 配布

- 開発用リポジトリと配布フォルダを分ける。配布フォルダには、実行に必要なものと利用者向けの操作マニュアルだけを入れる（設計書・テスト・ソースは入れない）。
- `python packaging/build.py` で、実行した OS 向けの配布フォルダ `dist/TraceabilityTool-<windows|linux>/` を作る。PyInstaller はクロスビルドできないため、Windows 版は Windows、Ubuntu 版は Ubuntu でビルドする。GitHub Actions（`.github/workflows/build.yml`）でも両 OS 版を作れる。
- 配布フォルダの構成: 実行ファイル（`TraceabilityTool.exe` / `TraceabilityTool`）、`_internal/`（Python 実行環境・ライブラリ・画面ファイル）、`packaging/user_files/` の中身（操作マニュアル）。
- `build/` と `dist/` は git の管理外。

## 2. ディレクトリ構成

```
tracetool/
  __main__.py          起動処理（引数解析、uvicorn 起動、ブラウザを開く）
  app.py               FastAPI アプリ生成、ルータ登録、静的ファイル配信
  db.py                接続、スキーマ作成・マイグレーション、トランザクション
  colschema.py         カラム定義の型・検証、値の正規化、ハッシュ計算
  readers.py           CSV / TSV / XLSX を「ヘッダ＋行の文字列配列」に変換
  importer.py          取り込みセッション、列の対応付け、検証、確定
  services/
    documents.py       文書・カラム定義の CRUD
    versions.py        版の一覧・削除・項目の取得（キャッシュ）
    relations.py       トレース関係の CRUD（循環チェック）
    links.py           リンクの CRUD、自動リンク再生成、要確認判定
    trace.py           未トレース・リンク切れ・網羅率の計算
    diff.py            版の差分計算
    export.py          Excel / CSV 出力
  static/
    index.html
    app.js             ルーティング、共通処理
    api.js             fetch のラッパ
    views/*.js         画面コンポーネント
    style.css
    vendor/vue.global.prod.js
packaging/
  build.py             配布フォルダを作る（PyInstaller）
  entry.py             実行ファイルのエントリポイント
  user_files/          配布フォルダにそのままコピーする利用者向け資料（操作マニュアル）
tests/
docs/
pyproject.toml
```

API は `app.py` に直接定義している（ルータへの分割はしていない）。

## 3. データモデル

### 3.1 カラム定義（JSON）

文書の「作業中のカラム定義」と、各版の「取り込み時点のカラム定義」は同じ JSON 形式で保存する。

```json
{
  "columns": [
    {
      "key": "c1a2b3",
      "name": "要件ID",
      "source_header": "要件ID",
      "type": "id",
      "list": null,
      "enum_values": null,
      "bool_values": null,
      "ref_document_id": null
    },
    {
      "key": "c9f8e7",
      "name": "上位要件",
      "source_header": "上位要件",
      "type": "string",
      "list": { "delimiters": [";", ","] },
      "ref_document_id": 3
    },
    {
      "key": "c5d4c3",
      "name": "必須",
      "source_header": "必須",
      "type": "bool",
      "bool_values": { "true": ["○", "◯", "Yes", "Y", "TRUE", "1"], "false": ["×", "✕", "No", "N", "FALSE", "0"] }
    }
  ]
}
```

| フィールド | 説明 |
|---|---|
| `key` | 列の内部キー。作成時にランダムな文字列を割り当て、以後変えない（F-06）。差分・ハッシュはこのキーで行う |
| `name` | 表示名 |
| `source_header` | 取り込み元ファイルのヘッダ名。列の自動対応付けに使う |
| `type` | `id` / `int` / `string` / `enum` / `bool` |
| `list` | リスト形式の場合に区切り文字の配列を指定する。`"\n"` は改行。`id` 型では指定不可 |
| `enum_values` | enum の選択肢 |
| `bool_values` | 真・偽とみなす文字列。比較は前後の空白を除き、英字は大文字小文字を区別しない |
| `ref_document_id` | 参照 ID 列の場合の参照先文書。この文書と参照先文書の間にトレース関係があることが必須 |

制約: `id` 型の列はちょうど 1 つ。`ref_document_id` は `string` 型にのみ指定できる。

### 3.2 値の正規化

取り込み時、セルの文字列を次の規則で変換して保存する。

1. 共通: 前後の空白を除去する。空文字は `null`。
2. リスト形式: 区切り文字で分割し、各要素の前後の空白を除去し、空要素を捨てる → 配列。要素ごとに 3〜6 を適用する。
3. `int`: Unicode NFKC 正規化（全角数字→半角）、桁区切りの `,` を除去、`1.0` のような整数値の小数は許可 → 整数。変換できなければ元の文字列のまま保存し、警告にする。
4. `bool`: `bool_values` と照合 → `true` / `false`。どちらにも一致しなければ元の文字列のまま保存し、警告にする。
5. `enum`: 選択肢と完全一致を確認する。一致しなければ値はそのまま保存し、警告にする。
6. `id` / `string`: 文字列のまま。

警告になったセルは、項目の `invalid` に列キーを記録し、画面で強調表示する。

### 3.3 内容ハッシュ（F-45）

```
content_hash = sha256( JSON.dumps( {列キー: 正規化後の値  ※値が null の列は除く}, sort_keys=True, ensure_ascii=False ) )
```

- 全列が対象（備考列を含む）。
- 列名の変更ではハッシュは変わらない（キーで持つため）。
- `null` の列を除外するので、空の列を追加しても既存項目のハッシュは変わらない。

### 3.4 テーブル定義（SQLite）

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);   -- schema_version など

CREATE TABLE documents (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  description   TEXT NOT NULL DEFAULT '',
  schema_json   TEXT NOT NULL,            -- 作業中のカラム定義（次回の取り込みで使う）
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);

CREATE TABLE versions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no      INTEGER NOT NULL,       -- 文書内で 1 から連番。削除しても欠番のまま再利用しない
  label           TEXT NOT NULL DEFAULT '',
  source_filename TEXT NOT NULL,
  import_settings TEXT NOT NULL,          -- JSON: 文字コード, ヘッダ行, シート名など
  schema_json     TEXT NOT NULL,          -- 取り込み時点のカラム定義
  row_count       INTEGER NOT NULL,
  imported_at     TEXT NOT NULL,
  UNIQUE (document_id, version_no)
);

CREATE TABLE items (
  version_id    INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
  item_id       TEXT NOT NULL,            -- ID 列の値
  row_no        INTEGER NOT NULL,         -- 取り込み順（表示順）
  data_json     TEXT NOT NULL,            -- {列キー: 正規化後の値}
  invalid_json  TEXT NOT NULL DEFAULT '[]', -- 警告になった列キーの配列
  content_hash  TEXT NOT NULL,
  PRIMARY KEY (version_id, item_id)
);

CREATE TABLE relations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  upper_doc_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  lower_doc_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  UNIQUE (upper_doc_id, lower_doc_id),
  CHECK (upper_doc_id <> lower_doc_id)
);

CREATE TABLE links (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  relation_id     INTEGER NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
  upper_item_id   TEXT NOT NULL,
  lower_item_id   TEXT NOT NULL,
  manual          INTEGER NOT NULL DEFAULT 0,  -- 手動で追加された
  auto_by_upper   INTEGER NOT NULL DEFAULT 0,  -- 上位文書の参照 ID 列から生成された
  auto_by_lower   INTEGER NOT NULL DEFAULT 0,  -- 下位文書の参照 ID 列から生成された
  auto_disabled   INTEGER NOT NULL DEFAULT 0,  -- 自動リンクを利用者が無効化した
  upper_hash_ack  TEXT,                        -- 確認時点の上位項目のハッシュ
  lower_hash_ack  TEXT,                        -- 確認時点の下位項目のハッシュ
  created_at      TEXT NOT NULL,
  UNIQUE (relation_id, upper_item_id, lower_item_id)
);
```

- 版の「最新版」は `version_no` が最大のもの。
- ID 列は `AUTOINCREMENT` にし、削除した文書・版・関係・リンクの ID を再利用しない（再利用すると、残っている参照が無関係の新しい行を指すため）。スキーマ版 1 の DB は、起動時に表を作り直して版 2 に移行する。
- 文書を削除するときは、他の文書の作業中カラム定義にある、その文書への `ref_document_id` を外す。
- 項目一覧の検索・ソート・絞り込みは、版単位で項目をメモリに読み込んで Python 側で行う（10,000 行程度なら十分に速い）。
- キャッシュ（接続オブジェクトに保持）:
  - 版 ID → 項目一覧・ハッシュ表。版は不変なので、版・文書の削除時とロールバック時のみ破棄する。
  - トレース評価の結果（関係ごと・文書ごと）。書き込みのトランザクションのたびに破棄する。

### 3.5 リンクの有効判定

1 つの（上位項目, 下位項目）の組に対してリンク行は 1 行だけとし、生成元をフラグで持つ。

```
有効 = manual OR ((auto_by_upper OR auto_by_lower) AND NOT auto_disabled)
```

| 操作 | 処理 |
|---|---|
| 手動で追加 | 行が無ければ作成。`manual=1`、`auto_disabled=0`、確認ハッシュに現在のハッシュを設定 |
| 手動で削除 | `manual=0`。自動フラグが立っていれば `auto_disabled=1`。すべてのフラグが 0 になったら行を削除 |
| 自動リンク生成 | 4.3 を参照 |
| 確認済みにする | 確認ハッシュを両項目の最新版のハッシュで更新 |

`auto_disabled` の行は、自動フラグが残っている間は保持する（再取り込み後も無効化を維持する: F-43）。

## 4. 処理

### 4.1 取り込みの流れ

取り込みは「セッション」単位で進める。アップロードされたファイルはメモリ上にのみ保持し、ディスクには書かない（F-18）。セッションは確定・取り消し・30 分の無操作で破棄する。

```
1. POST /api/imports                  ファイルをアップロード → セッション ID、形式、シート一覧、先頭 30 行の生データ
2. PUT  /api/imports/{sid}/settings   文字コード・ヘッダ行・シート（複数可）を指定 → ヘッダ一覧、列の対応付け案
3. PUT  /api/imports/{sid}/validate   列の対応付け（各列の source_header）とカラム定義の変更を指定 → 検証結果（エラー・警告）、プレビュー
4. POST /api/imports/{sid}/commit     ラベルを指定して確定 → 新しい版を作成
   DELETE /api/imports/{sid}          取り消し
```

#### 読み込み（readers.py）

- CSV / TSV: `csv` モジュールで読む。セル内の改行（引用符で囲まれたもの）に対応する。文字コードは指定がなければ UTF-8 BOM → UTF-8 → CP932 の順にデコードを試す。
- XLSX: openpyxl で `data_only=True`（数式は計算済みの値）で開く。結合セルは `merged_cells.ranges` から結合範囲内の全セルに左上の値を展開する。日付は `YYYY-MM-DD`（時刻があれば `YYYY-MM-DD HH:MM:SS`）、整数値の float は整数の文字列にする。
- 複数シートは、各シートでヘッダ行の位置が同じである前提で、行を順に連結する。ヘッダが一致しないシートがあればエラーとする。
- ヘッダ行より後の、全セルが空の行は捨てる。

#### 列の対応付け（importer.py）

1. ファイルのヘッダごとに、カラム定義の `source_header` と一致する列を探す。無ければ `name` と一致する列を探す。
2. 一致しないヘッダは画面で「既存の列に割り当てる / 新しい列として追加（既定は string 型）/ 無視」から選ぶ。
3. ファイルに対応するヘッダが無い列は「今回は値なし」とし、警告を出す。
4. 確定時に、変更後のカラム定義を文書の作業中定義として保存し、同じものを版にも保存する。

#### 検証

| 区分 | 内容 |
|---|---|
| エラー | ID 列が無い / ID 列が対応付けられていない / ID の空欄 / ID の重複 / 複数シートのヘッダ不一致 / 参照 ID 列の参照先とのトレース関係が無い |
| 警告 | 整数に変換できない / bool に変換できない / 定義外の enum 値 / 参照 ID が参照先文書の最新版に存在しない / ファイルに無い列がある |

エラーがあれば確定できない。警告は件数と該当行（最大 1,000 件）を表示する。

#### 確定（1 トランザクション: N-04）

1. `versions` に行を追加（`version_no` = 既存の最大値 + 1）。
2. `items` に全行を一括挿入。
3. `documents.schema_json` を更新。
4. 自動リンクを再生成する（4.3）。
5. コミット。途中で例外が起きたらロールバックする。

### 4.2 版の削除

最新版を削除した場合は、その文書の自動リンクを新しい最新版から再生成する（4.3）。版が 1 つも無くなった場合は、その文書が生成元の自動フラグをすべて 0 にする。

### 4.3 自動リンクの再生成

文書 D の最新版を対象に、D の参照 ID 列ごとに次を行う。

1. 参照先文書 R と D の間のトレース関係を特定する（D が上位なら `auto_by_upper`、D が下位なら `auto_by_lower` を使う）。
2. D の各項目について、参照 ID 列の値（リスト形式なら各要素）から（上位 ID, 下位 ID）の組の集合 S を作る。
3. 既存のリンクのうち、該当フラグが 1 で S に含まれない行はフラグを 0 にする（すべてのフラグが 0 になり `manual=0` なら行を削除）。
4. S に含まれる組は、行が無ければ作成し、該当フラグを 1 にする。新しく作成した行の確認ハッシュは現在のハッシュとする。既存行の確認ハッシュと `auto_disabled` は変えない。
5. 確認ハッシュが空（NULL）のリンクのうち、D 側の項目が D の最新版に存在するものに、現在のハッシュを入れる。
   - リンクを作った時点で相手の項目がまだ無かった場合（相手文書が未取り込み、リンク切れのまま作成・確認した場合）、確認ハッシュは空になる。項目が現れた時点のハッシュを基準にしないと、取り込みの順番だけでリンクが要確認になってしまうため。

この処理は、取り込みの確定時、版の削除時、関係の作成時に行う。

トレース関係を削除した場合、その関係のリンクはすべて削除される（ON DELETE CASCADE）。

### 4.4 トレースの評価（trace.py）

トレース関係 (U → L) ごとに、U と L の最新版を使って計算する。

| 判定 | 条件 |
|---|---|
| 上位未トレース | U の最新版の項目で、有効なリンクのうち下位項目が L の最新版に存在するものが 0 本 |
| 下位未トレース | L の最新版の項目で、有効なリンクのうち上位項目が U の最新版に存在するものが 0 本 |
| リンク切れ | 有効なリンクで、上位項目または下位項目が最新版に存在しない |
| 要確認 | 有効なリンクで、両項目とも存在し、どちらかの最新ハッシュが確認ハッシュと異なる |

網羅率 = （未トレースでない項目数）/（項目数）。上位側・下位側それぞれ計算する。
項目に複数の上位文書（または下位文書）がある場合は、関係ごとに判定し、項目一覧では「いずれかの関係で未トレース」を未トレースとして表示する。

### 4.5 差分（diff.py）

版 A（旧）と版 B（新）について次を求める。

- 列: 列キーで比較し、追加 / 削除 / 名前変更 / 型変更を求める。
- 項目: ID で比較する。
  - B にのみある → 追加
  - A にのみある → 削除
  - 両方にあり、ハッシュが異なる → 変更（値が異なる列キーとその前後の値を返す）
  - ハッシュが同じ → 変更なし（画面では既定で非表示）

### 4.6 出力（export.py）

| 出力 | 内容 |
|---|---|
| トレースマトリクス | 関係を指定する。1 行 1 リンク: 上位 ID、上位の表示列、下位 ID、下位の表示列、生成元（手動/自動）、状態（正常/要確認/リンク切れ）。上位未トレース・下位未トレースの項目も相手側を空欄にして含める |
| 未トレース一覧 | 関係ごとのシート（CSV の場合は 1 ファイルに「関係」列を付ける）: 区分、文書、ID、表示列。先頭に網羅率の集計 |
| 差分 | 区分（追加/削除/変更）、ID、列名、変更前、変更後 |

「表示列」は文書ごとに 1 列選べる（カラム定義の任意の string 列。既定は ID 列の次の列）。カラム定義 JSON に `"display_column": "<列キー>"` として持つ。
Excel は openpyxl で作成し、ブラウザにダウンロードさせる（サーバ側には保存しない）。CSV は UTF-8 BOM 付き（Excel で文字化けしないため）。

- Excel のセルに書けない制御文字は取り除く。
- 数式として解釈されうる値（数式インジェクション）:
  - Excel: `=` で始まる文字列も、文字列型のセルとして書く（値は変えない）。
  - CSV: `=` `+` `-` `@` タブ・CR で始まる文字列の先頭に `'` を付ける（値が変わることを操作マニュアルに記載する）。

## 5. API 一覧

すべて JSON。パスの接頭辞は `/api`。

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/documents` | 文書一覧（最新版、項目数、網羅率の要約を含む） |
| POST | `/documents` | 文書を作成（名前、説明、カラム定義） |
| GET | `/documents/{id}` | 文書の詳細（作業中のカラム定義を含む） |
| PUT | `/documents/{id}` | 名前・説明・カラム定義を更新 |
| DELETE | `/documents/{id}` | 文書を削除 |
| GET | `/documents/{id}/versions` | 版の一覧 |
| DELETE | `/versions/{vid}` | 版を削除 |
| GET | `/documents/{id}/find?q=` | リンク追加用に、最新版から ID・表示列で項目を検索（最大 30 件） |
| GET | `/versions/{vid}/items` | 項目一覧。クエリ: `q`（全文）、`f.<列キー>`（列ごとの部分一致。`f.__invalid` で警告セルのある行のみ）、`sort`（列キー / `upper_count` / `lower_count`）、`desc`、`trace`（`no_upper` / `no_lower` / `suspect` / `broken`）、`page`、`size` |
| GET | `/versions/{vid}/item?id=` | 項目の詳細と、関係ごとの上位・下位のリンク（状態付き。無効化した自動リンクも含む） |
| GET | `/diff?from={vid}&to={vid}` | 差分 |
| GET | `/relations` | トレース関係の一覧 |
| POST | `/relations` | 関係を作成（循環ならエラー） |
| DELETE | `/relations/{rid}` | 関係を削除 |
| POST | `/links` | 手動リンクを追加（関係、上位 ID、下位 ID） |
| DELETE | `/links/{lid}` | リンクを削除（3.5 の規則） |
| POST | `/links/{lid}/restore` | 無効化した自動リンクを元に戻す |
| POST | `/links/{lid}/ack` | 確認済みにする |
| POST | `/links/ack` | 一括で確認済みにする（ID の配列） |
| GET | `/trace/{rid}` | 関係ごとの網羅率と、未トレース・リンク切れ・要確認の一覧 |
| POST | `/imports` ほか | 4.1 を参照 |
| GET | `/export/matrix?relation={rid}&format=xlsx\|csv` | トレースマトリクス |
| GET | `/export/untraced?relation={rid}&format=...` | 未トレース一覧（`relation` 省略で全関係） |
| GET | `/export/diff?from={vid}&to={vid}&format=...` | 差分 |

項目 ID はパスではなくクエリで渡す（ID に `/` などが含まれ得るため）。
取り込みの検証は `PUT /imports/{sid}/validate`（本文: `schema`）。関係を作成したときは、両文書の自動リンクを再生成する。

## 6. 画面

ハッシュ形式のルーティング（`#/documents/3/items` など）で、1 枚の HTML 内で画面を切り替える。

| ID | 画面 | 主な内容 |
|---|---|---|
| S1 | ダッシュボード | 文書の一覧（最新版、項目数、上位なし・下位なし・要確認・リンク切れの件数。件数をクリックすると S4 を絞り込んで開く）。トレース関係を「上位 → 下位」の一覧で表示し、各関係の網羅率を表示。S7 の機能（関係の追加・削除）も同じ画面に置く |
| S2 | 文書の設定 | 名前・説明。カラム定義の編集（列の追加・削除・並べ替え、型、リスト形式と区切り文字、enum の選択肢、bool の真偽文字列、参照先文書、表示列） |
| S3 | 取り込み | 4.1 の 4 ステップのウィザード。ステップ 3 で列の対応付けと検証結果を表示 |
| S4 | 項目一覧 | 版の選択（既定は最新版。過去の版は読み取り専用の表示）、全文検索、列ごとのフィルタ、ソート、ページング（100 件ずつ）。「上位リンク数」「下位リンク数」「状態」の列を付け、状態で絞り込める。警告セルは強調表示 |
| S5 | 項目詳細 | S4 の右側のパネル。全列の値。関係ごとに上位・下位のリンク一覧（相手の ID と表示列、状態、生成元）。リンク先をクリックすると相手文書の S4 に遷移してその項目を選択する。リンクの追加（相手文書の項目を ID・表示列で検索して選ぶ）・削除・確認済み |
| S6 | 版の一覧・差分 | 版の一覧（ラベル、日時、元ファイル名、行数）、版の削除。2 つの版を選んで差分を表示（列の変更、項目の追加・削除・変更。変更はセル単位で前後を表示）。差分の出力 |
| S7 | トレース関係 | 関係の追加・削除 |
| S8 | トレース状況 | 関係を選択し、網羅率、上位未トレース、下位未トレース、リンク切れ、要確認の各タブ。要確認は一括で確認済みにできる。マトリクス・未トレース一覧の出力 |

## 7. エラー処理・ログ

- API のエラーは `{ "error": { "code": "...", "message": "日本語のメッセージ" } }` で返し、画面にトースト表示する。
- ログはデータフォルダの `logs/` に出力する。**ログには項目の値を書かない**（機密情報をログに残さないため）。書くのは操作の種類、文書 ID、件数、エラーの種類まで。
  - 予期しない例外は、例外メッセージ（値を含みうる）を書かず、例外の型と発生場所（ファイル名・行番号・関数名）だけを記録する。応答にも例外の型だけを返す。
  - リクエスト本文の型の誤り（422）は、項目名だけを返し、入力値は返さない。

## 7.1 ローカル Web サーバとしての対策

| 脅威 | 対策 |
|---|---|
| 他の PC からの接続 | `127.0.0.1` にのみバインドする |
| DNS リバインディング（悪意あるサイトが自分のドメインを 127.0.0.1 に向け、同一オリジンとして API を読む） | `Host` ヘッダが `127.0.0.1` / `localhost` 以外の要求を 400 で拒否する |
| CSRF（他サイトから書き込み API を呼ぶ） | GET 以外の要求で、`Origin` がこのツール（ホスト名とポート）以外、または `Sec-Fetch-Site: cross-site` の場合は 403 で拒否する |
| XSS | 画面では値を `{{ }}` で表示し、`v-html` / `innerHTML` を使わない |

## 8. テスト方針

- 単体テスト（pytest）: 値の正規化、ハッシュ、各形式の読み込み（結合セル・CP932・セル内改行）、列の対応付け、検証、自動リンクの再生成、手動リンクの削除規則、トレース評価、差分。
- API テスト: FastAPI の TestClient で、取り込み → 版の追加 → リンクの引き継ぎ・要確認 → 出力 の一連の流れを確認する。
- 回帰テスト（`tests/test_regressions.py`）: 取り込みの順序と要確認、フラグの組み合わせ、複数の関係、文書の削除と ID、DB の移行、出力の内容（制御文字・数式）、Host / Origin の検査、ログに値が書かれないこと、読み込みの細かな条件。
- テストデータはテスト内で生成する（実際の仕様書は使わない）。

## 9. 実装順序

1. 基盤: `db.py`、`colschema.py`、起動処理
2. 取り込み: `readers.py`、`importer.py`、文書・版の API
3. 画面: S1、S2、S3、S4（閲覧まで）
4. トレース: 関係、リンク、自動生成、評価、S5、S7、S8
5. 差分: `diff.py`、S6
6. 出力: `export.py`
