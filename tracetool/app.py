"""FastAPI アプリ。API は services を呼ぶだけの薄い層にする。"""

from __future__ import annotations

import hashlib
import logging
import traceback
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import importer
from .db import Database
from .errors import AppError
from .services import diff as diff_svc
from .services import documents as doc_svc
from .services import export as export_svc
from .services import items as items_svc
from .services import links as link_svc
from .services import relations as rel_svc
from .services import trace as trace_svc
from .services import versions as ver_svc

STATIC_DIR = Path(__file__).parent / "static"


def static_version() -> str:
    """画面ファイルの内容から版番号を作る。

    画面ファイルは /static/<版番号>/ の下で配信する。ツールを新しい版に差し替えると URL が変わるため、
    ブラウザに残った古いファイル（JS モジュールはキャッシュされやすい）を使うことが無い。
    """
    h = hashlib.sha1()
    for f in sorted(STATIC_DIR.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(STATIC_DIR).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]
log = logging.getLogger("tracetool")


def _from_param(request: Request) -> int:
    # from は Python の予約語なので、クエリから直接読む
    try:
        return int(request.query_params["from"])
    except (KeyError, ValueError):
        raise AppError("比較元の版（from）を指定してください") from None


# --- リクエスト本文 ------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class DocumentIn(_Body):
    name: str
    description: str | None = None
    schema_: dict | None = Field(default=None, alias="schema")


class RelationIn(_Body):
    upper_doc_id: int
    lower_doc_id: int


class LinkIn(_Body):
    relation_id: int
    upper_item_id: str
    lower_item_id: str


class AckIn(_Body):
    ids: list[int]


class ImportSettingsIn(_Body):
    encoding: str | None = None
    header_row: int = Field(default=1, ge=1)
    sheets: list[str] = []


class ImportTextIn(_Body):
    document_id: int
    text: str
    format: str = "auto"


class ColumnIn(_Body):
    column: dict


class ImportSchemaIn(_Body):
    schema_: dict = Field(alias="schema")
    label: str = ""


# --- エラー・ログ ----------------------------------------------------------------


def _error(message: str, code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _log_unexpected(request: Request, exc: BaseException) -> None:
    """予期しない例外を記録する。

    例外メッセージやローカル変数には項目の値が含まれうるため書かない。
    書くのは例外の型と、発生場所（ファイル名・行番号・関数名）だけ。
    """
    frames = traceback.extract_tb(exc.__traceback__)[-8:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(frames))
    log.error("unexpected error: %s %s %s at %s", request.method, request.url.path, type(exc).__name__, where)


def create_app(db: Database, port: int | None = None, extra_hosts: tuple[str, ...] = ()) -> FastAPI:
    """port: 待ち受けポート（Origin の検査に使う）。extra_hosts: テスト用に許可する Host 名。"""
    app = FastAPI(title="トレーサビリティツール", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = importer.SessionStore()
    sessions.start_reaper()
    allowed_hosts = {"127.0.0.1", "localhost", *extra_hosts}
    static_prefix = f"/static/{static_version()}"

    def _host_ok(hostname: str | None) -> bool:
        return (hostname or "").lower() in allowed_hosts

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # DNS リバインディング対策: このツール以外の名前でアクセスされたら応答しない
        host = request.headers.get("host", "")
        if not _host_ok(urlsplit("//" + host).hostname):
            return _error("許可されていないホスト名でのアクセスです", "forbidden_host", 400)
        # CSRF 対策: 状態を変える要求は、このツールの画面から送られたものだけ受け付ける
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("sec-fetch-site") == "cross-site":
                return _error("他のサイトからの操作は受け付けません", "forbidden_origin", 403)
            origin = request.headers.get("origin")
            if origin is not None:
                o = urlsplit(origin)
                if not _host_ok(o.hostname) or (port is not None and o.port != port):
                    return _error("他のサイトからの操作は受け付けません", "forbidden_origin", 403)
        try:
            response = await call_next(request)
            if request.url.path.startswith("/static/"):
                # ツールを新しい版に差し替えたとき、ブラウザに残った古い画面ファイルを使わせない
                # （毎回更新の有無を確認する。変わっていなければ 304 で済む）
                response.headers["Cache-Control"] = "no-cache"
            return response
        except Exception as exc:  # noqa: BLE001 - 予期しない例外はすべてここで 500 にする
            _log_unexpected(request, exc)
            return _error(f"予期しないエラーが発生しました（{type(exc).__name__}）", "internal", 500)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error(exc.message, exc.code, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # 入力値そのものは返さず、項目名だけ伝える
        fields = sorted({".".join(str(p) for p in e.get("loc", ()) if p != "body") for e in exc.errors()})
        return _error("入力が不正です: " + ", ".join(f or "(本文)" for f in fields), "invalid_request", 422)

    # --- 文書 ---------------------------------------------------------------

    @app.get("/api/documents")
    def list_documents():
        with db.read() as conn:
            docs = doc_svc.list_documents(conn)
            for d in docs:
                v = ver_svc.latest_version(conn, d["id"])
                d["latest"] = (
                    {k: v[k] for k in ("id", "version_no", "label", "row_count", "imported_at")} if v else None
                )
                d["trace"] = trace_svc.document_summary(conn, d["id"]) if v else None
                d["version_count"] = conn.execute(
                    "SELECT COUNT(*) FROM versions WHERE document_id = ?", (d["id"],)
                ).fetchone()[0]
            return docs

    @app.post("/api/documents")
    def create_document(body: DocumentIn):
        with db.tx() as conn:
            doc_id = doc_svc.create_document(conn, body.name, body.description or "", body.schema_)
        log.info("document created: id=%s", doc_id)
        return {"id": doc_id}

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: int):
        with db.read() as conn:
            d = doc_svc.get_document(conn, doc_id)
            v = ver_svc.latest_version(conn, doc_id)
            d["latest_version_id"] = v["id"] if v else None
            d["referenced_by"] = doc_svc.referencing_documents(conn, doc_id)
            return d

    @app.put("/api/documents/{doc_id}")
    def update_document(doc_id: int, body: DocumentIn):
        with db.tx() as conn:
            doc_svc.update_document(conn, doc_id, body.name, body.description, body.schema_)
        return {"ok": True}

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: int):
        with db.tx() as conn:
            doc_svc.delete_document(conn, doc_id)
        log.info("document deleted: id=%s", doc_id)
        return {"ok": True}

    @app.get("/api/documents/{doc_id}/versions")
    def list_versions(doc_id: int):
        with db.read() as conn:
            doc_svc.get_document(conn, doc_id)
            return ver_svc.list_versions(conn, doc_id)

    @app.get("/api/documents/{doc_id}/distinct")
    def distinct_values(doc_id: int, key: str):
        with db.read() as conn:
            return items_svc.distinct_values(conn, doc_id, key)

    @app.get("/api/documents/{doc_id}/neighborhood")
    def item_neighborhood(doc_id: int, id: str):
        # 横並び表示用。項目 ID は / を含み得るためクエリで受け取る
        with db.read() as conn:
            return items_svc.item_neighborhood(conn, doc_id, id)

    @app.get("/api/documents/{doc_id}/find")
    def find_items(doc_id: int, q: str = ""):
        with db.read() as conn:
            return items_svc.find_items(conn, doc_id, q)

    # --- 版・項目 -----------------------------------------------------------

    @app.delete("/api/versions/{vid}")
    def delete_version(vid: int):
        with db.tx() as conn:
            doc_id = ver_svc.delete_version(conn, vid)
            link_svc.regenerate_auto_links(conn, doc_id)
        log.info("version deleted: id=%s", vid)
        return {"ok": True}

    @app.get("/api/versions/{vid}/items")
    def query_items(
        request: Request,
        vid: int,
        q: str = "",
        sort: str | None = None,
        desc: bool = False,
        trace: str | None = None,
        page: int = 1,
        size: int = 100,
    ):
        filters = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f.")}
        with db.read() as conn:
            return items_svc.query_items(conn, vid, q, filters, sort, desc, trace, page, size)

    @app.get("/api/versions/{vid}/item")
    def item_detail(vid: int, id: str):
        # 項目 ID に / などが含まれ得るため、パスではなくクエリで受け取る
        with db.read() as conn:
            return items_svc.item_detail(conn, vid, id)

    @app.get("/api/diff")
    def diff(request: Request, to: int):
        from_vid = _from_param(request)
        with db.read() as conn:
            return diff_svc.diff_versions(conn, from_vid, to)

    # --- トレース関係・リンク -----------------------------------------------

    @app.get("/api/relations")
    def list_relations():
        with db.read() as conn:
            out = []
            for r in rel_svc.list_relations(conn):
                s = trace_svc.relation_summary(conn, r["id"])
                s["upper_name"] = doc_svc.get_document(conn, r["upper_doc_id"])["name"]
                s["lower_name"] = doc_svc.get_document(conn, r["lower_doc_id"])["name"]
                out.append(s)
            return out

    @app.post("/api/relations")
    def create_relation(body: RelationIn):
        with db.tx() as conn:
            rid = rel_svc.create_relation(conn, body.upper_doc_id, body.lower_doc_id)
            # 既に取り込み済みの参照 ID 列があれば、関係の作成時点でリンクを作る
            link_svc.regenerate_auto_links(conn, body.upper_doc_id)
            link_svc.regenerate_auto_links(conn, body.lower_doc_id)
        return {"id": rid}

    @app.delete("/api/relations/{rid}")
    def delete_relation(rid: int):
        with db.tx() as conn:
            rel_svc.delete_relation(conn, rid)
        return {"ok": True}

    @app.get("/api/trace/{rid}")
    def evaluate_relation(rid: int):
        with db.read() as conn:
            ev = trace_svc.evaluate_relation(conn, rid)
            ev["upper"]["name"] = doc_svc.get_document(conn, ev["relation"]["upper_doc_id"])["name"]
            ev["lower"]["name"] = doc_svc.get_document(conn, ev["relation"]["lower_doc_id"])["name"]
            ev["upper"]["labels"] = export_svc.item_labels(conn, ev["relation"]["upper_doc_id"])
            ev["lower"]["labels"] = export_svc.item_labels(conn, ev["relation"]["lower_doc_id"])
            return ev

    @app.post("/api/links")
    def add_link(body: LinkIn):
        with db.tx() as conn:
            lid = link_svc.add_manual_link(conn, body.relation_id, body.upper_item_id, body.lower_item_id)
        return {"id": lid}

    @app.delete("/api/links/{lid}")
    def remove_link(lid: int):
        with db.tx() as conn:
            link_svc.remove_link(conn, lid)
        return {"ok": True}

    @app.post("/api/links/{lid}/restore")
    def restore_link(lid: int):
        with db.tx() as conn:
            link_svc.restore_auto_link(conn, lid)
        return {"ok": True}

    @app.post("/api/links/ack")
    def ack_links(body: AckIn):
        with db.tx() as conn:
            n = link_svc.ack_links(conn, body.ids)
        return {"count": n}

    # --- 取り込み -----------------------------------------------------------

    @app.post("/api/imports")
    async def import_start(document_id: int = Form(...), file: UploadFile = File(...)):
        data = await file.read()
        with db.read() as conn:
            result = importer.start(conn, sessions, document_id, file.filename or "", data)
        log.info("import started: document=%s format=%s size=%s", document_id, result["format"], len(data))
        return result

    @app.put("/api/imports/{sid}/settings")
    def import_settings(sid: str, body: ImportSettingsIn):
        session = sessions.get(sid)
        with db.read() as conn:
            return importer.apply_settings(conn, session, body.encoding or None, body.header_row, body.sheets)

    @app.post("/api/imports/text")
    def import_start_text(body: ImportTextIn):
        with db.read() as conn:
            result = importer.start_text(conn, sessions, body.document_id, body.text, body.format)
        log.info("import started (text): document=%s format=%s", body.document_id, result["format"])
        return result

    @app.put("/api/imports/{sid}/distinct")
    def import_distinct(sid: str, body: ColumnIn):
        session = sessions.get(sid)
        return importer.distinct_values(session, body.column)

    @app.put("/api/imports/{sid}/validate")
    def import_validate(sid: str, body: ImportSchemaIn):
        session = sessions.get(sid)
        with db.read() as conn:
            return importer.validate(conn, session, body.schema_)

    @app.post("/api/imports/{sid}/commit")
    def import_commit(sid: str, body: ImportSchemaIn):
        session = sessions.get(sid)
        with db.tx() as conn:
            vid = importer.commit(conn, session, body.schema_, body.label)
        sessions.remove(sid)
        log.info("import committed: document=%s version=%s", session.document_id, vid)
        return {"version_id": vid}

    @app.delete("/api/imports/{sid}")
    def import_cancel(sid: str):
        sessions.remove(sid)
        return {"ok": True}

    # --- 出力 ---------------------------------------------------------------

    def _download(sheets, fmt: str, basename: str) -> Response:
        content, ext, media = export_svc.render(sheets, fmt)
        filename = f"{basename}.{ext}"
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f"attachment; filename=\"export.{ext}\"; filename*=UTF-8''{quote(filename)}"},
        )

    @app.get("/api/export/matrix")
    def export_matrix(relation: int, format: str = "xlsx"):
        with db.read() as conn:
            sheets = export_svc.matrix_sheets(conn, relation)
        return _download(sheets, format, f"トレースマトリクス_{sheets[0].title}")

    @app.get("/api/export/untraced")
    def export_untraced(relation: int | None = None, format: str = "xlsx"):
        with db.read() as conn:
            sheets = export_svc.untraced_sheets(conn, relation)
            if relation:
                rel = rel_svc.get_relation(conn, relation)
                up = doc_svc.get_document(conn, rel["upper_doc_id"])["name"]
                lo = doc_svc.get_document(conn, rel["lower_doc_id"])["name"]
                # 複数の関係を続けて出力しても取り違えないよう、関係名をファイル名に含める
                name = f"未トレース一覧_{up}→{lo}"
            else:
                name = "未トレース一覧_全関係"
        return _download(sheets, format, name)

    @app.get("/api/export/diff")
    def export_diff(request: Request, to: int, format: str = "xlsx"):
        from_vid = _from_param(request)
        with db.read() as conn:
            sheets = export_svc.diff_sheets(conn, from_vid, to)
            doc = doc_svc.get_document(conn, ver_svc.get_version(conn, to)["document_id"])
        return _download(sheets, format, f"{doc['name']}_{sheets[0].title}")

    # --- 画面 ---------------------------------------------------------------

    @app.get("/")
    def index():
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace('"/static/', f'"{static_prefix}/')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount(static_prefix, StaticFiles(directory=STATIC_DIR), name="static")
    return app
