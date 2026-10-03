"""FastAPI アプリ。API は services を呼ぶだけの薄い層にする。"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

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
log = logging.getLogger("tracetool")


def _from_param(request: Request) -> int:
    # from は Python の予約語なので、クエリから直接読む
    try:
        return int(request.query_params["from"])
    except (KeyError, ValueError):
        raise AppError("比較元の版（from）を指定してください") from None


def create_app(db: Database) -> FastAPI:
    app = FastAPI(title="トレーサビリティツール", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = importer.SessionStore()

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        # ログには値を書かず、例外の種類と場所だけ残す
        log.exception("unexpected error: %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": {"code": "internal", "message": f"予期しないエラーが発生しました（{type(exc).__name__}）"}},
            status_code=500,
        )

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
    def create_document(body: dict = Body(...)):
        with db.tx() as conn:
            doc_id = doc_svc.create_document(conn, body.get("name", ""), body.get("description", ""), body.get("schema"))
        log.info("document created: id=%s", doc_id)
        return {"id": doc_id}

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: int):
        with db.read() as conn:
            d = doc_svc.get_document(conn, doc_id)
            v = ver_svc.latest_version(conn, doc_id)
            d["latest_version_id"] = v["id"] if v else None
            return d

    @app.put("/api/documents/{doc_id}")
    def update_document(doc_id: int, body: dict = Body(...)):
        with db.tx() as conn:
            doc_svc.update_document(conn, doc_id, body.get("name", ""), body.get("description", ""), body.get("schema") or {})
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
    def create_relation(body: dict = Body(...)):
        with db.tx() as conn:
            rid = rel_svc.create_relation(conn, int(body["upper_doc_id"]), int(body["lower_doc_id"]))
            # 既に取り込み済みの参照 ID 列があれば、関係の作成時点でリンクを作る
            link_svc.regenerate_auto_links(conn, int(body["upper_doc_id"]))
            link_svc.regenerate_auto_links(conn, int(body["lower_doc_id"]))
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
    def add_link(body: dict = Body(...)):
        with db.tx() as conn:
            lid = link_svc.add_manual_link(
                conn, int(body["relation_id"]), str(body["upper_item_id"]), str(body["lower_item_id"])
            )
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
    def ack_links(body: dict = Body(...)):
        with db.tx() as conn:
            n = link_svc.ack_links(conn, [int(i) for i in body.get("ids", [])])
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
    def import_settings(sid: str, body: dict = Body(...)):
        session = sessions.get(sid)
        with db.read() as conn:
            return importer.apply_settings(
                conn, session, body.get("encoding") or None, int(body.get("header_row", 1)), body.get("sheets") or []
            )

    @app.put("/api/imports/{sid}/validate")
    def import_validate(sid: str, body: dict = Body(...)):
        session = sessions.get(sid)
        with db.read() as conn:
            return importer.validate(conn, session, body.get("schema") or {})

    @app.post("/api/imports/{sid}/commit")
    def import_commit(sid: str, body: dict = Body(...)):
        session = sessions.get(sid)
        with db.tx() as conn:
            vid = importer.commit(conn, session, body.get("schema") or {}, body.get("label", ""))
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
        return _download(sheets, format, "未トレース一覧")

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
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
