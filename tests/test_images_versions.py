"""画像のパスの列と、版の整理（選んだ版だけ残して v1 にする）。"""

from .conftest import make_csv
from .test_flow import do_import, link_doc, ok, req_csv, scr_xlsx, setup

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def image_doc(client, base_dir):
    return ok(client.post("/api/documents", json={"name": "画面", "schema": {"columns": [
        {"key": "id", "name": "ID", "type": "id"},
        {"key": "img", "name": "画面イメージ", "type": "string", "image": {"base_dir": str(base_dir)}},
    ]}}))["id"]


def test_image_column(client, tmp_path):
    base = tmp_path / "images"
    (base / "screen").mkdir(parents=True)
    (base / "screen" / "login.png").write_bytes(PNG)
    (base / "memo.txt").write_text("x")
    (tmp_path / "secret.png").write_bytes(PNG)
    doc = image_doc(client, base)
    do_import(client, doc, "a.csv", make_csv([["ID", "画面イメージ"], ["S1", r"screen\login.png"]]))
    # 表示用のカラム定義に画像の設定が入る
    cols = ok(client.get(f"/api/documents/{doc}/latest-items"))["schema"]["columns"]
    assert cols[1]["image"] == {"base_dir": str(base)}

    def get(path, **headers):
        return client.get("/api/image", params={"doc": doc, "key": "img", "path": path}, headers=headers)

    r = get(r"screen\login.png")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert get("screen/login.png").status_code == 200
    # 基準フォルダの外・画像でないファイル・無いファイル・他のサイトからは表示しない
    assert get("../secret.png").status_code == 400
    assert get(str(tmp_path / "secret.png")).status_code == 400
    assert get("memo.txt").status_code == 400
    assert get("none.png").status_code == 404
    assert get("screen/login.png", **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    r = client.get("/api/image", params={"doc": doc, "key": "id", "path": "x.png"})
    assert r.status_code == 400 and "画像の列" in r.json()["error"]["message"]


def test_image_column_requires_absolute_base_dir(client):
    r = client.post("/api/documents", json={"name": "画面", "schema": {"columns": [
        {"key": "id", "name": "ID", "type": "id"},
        {"key": "img", "name": "画面イメージ", "type": "string", "image": {"base_dir": "images"}},
    ]}})
    assert r.status_code == 400 and "絶対パス" in r.json()["error"]["message"]


def test_make_first_version(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, req, "req.csv", req_csv("2"))
    v3 = do_import(client, req, "req.csv", req_csv("3"), label="第3版")["version_id"]
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)
    ok(client.post(f"/api/versions/{v3}/make-first"))
    versions = ok(client.get(f"/api/documents/{req}/versions"))
    assert [(v["id"], v["version_no"], v["label"]) for v in versions] == [(v3, 1, "第3版")]
    # 次の取り込みは v2 になる（消した版の番号の記録も振り直す）
    do_import(client, req, "req.csv", req_csv("4"))
    assert [v["version_no"] for v in ok(client.get(f"/api/documents/{req}/versions"))] == [2, 1]
    # 古い版を選んだ場合は、それが最新版になり、リンクも作り直される
    link = link_doc(client, scr)
    first = ok(client.get(f"/api/documents/{link}/versions"))[0]["id"]
    do_import(client, link, "l.csv", make_csv([["画面ID", "画面名", "上位要件"], ["SCR-01", "x", "REQ-001"]]))
    assert len(ok(client.get(f"/api/trace/{rel}"))["links"]) == 1
    ok(client.post(f"/api/versions/{first}/make-first"))
    assert len(ok(client.get(f"/api/trace/{rel}"))["links"]) == 4
    assert client.post("/api/versions/9999/make-first").status_code == 404
