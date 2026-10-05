"""項目一覧の編集モード（POST /api/documents/{id}/edit）と、選択式の絞り込み。"""

from .test_flow import do_import, ok, req_csv, scr_xlsx, setup


def latest(client, doc):
    return ok(client.get(f"/api/documents/{doc}/latest-items"))


def edit(client, doc, base, mode="new", mutate=None, label=""):
    rows = [{"data": dict(i["data"])} for i in base["items"]]
    schema = base["schema"]
    if mutate:
        mutate(schema, rows)
    return client.post(
        f"/api/documents/{doc}/edit",
        json={"base_version_id": base["version_id"], "mode": mode, "schema": schema, "items": rows, "label": label},
    )


def test_edit_as_new_version(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    base = latest(client, req)

    def mutate(schema, rows):
        rows[0]["data"]["rname"] = "ログイン（改）"
        rows[1]["data"]["rpri"] = "最高"  # 選択肢に足す
        rows[2]["data"]["rmust"] = False
        schema["columns"][2]["enum_values"].append("最高")
        schema["columns"].append({"key": "cnew", "name": "担当", "type": "string"})
        rows.append({"data": {"rid": "REQ-004", "rname": "印刷", "cnew": "山田"}})

    r = ok(edit(client, req, base, "new", mutate, label="画面で修正"))
    assert r["version_no"] == 2 and r["mode"] == "new"
    after = latest(client, req)
    assert after["version_id"] == r["version_id"]
    by_id = {i["item_id"]: i for i in after["items"]}
    assert by_id["REQ-001"]["data"]["rname"] == "ログイン（改）"
    assert by_id["REQ-002"]["data"]["rpri"] == "最高" and by_id["REQ-002"]["invalid"] == []
    assert by_id["REQ-003"]["data"]["rmust"] is False
    assert by_id["REQ-004"]["data"]["cnew"] == "山田"
    # 足した列と選択肢は、文書の作業中のカラム定義にも入る（次回の取り込みで使う）
    working = ok(client.get(f"/api/documents/{req}"))["schema"]
    assert "最高" in working["columns"][2]["enum_values"]
    assert working["columns"][-1]["name"] == "担当"
    # 差分で編集前と比べられる
    versions = ok(client.get(f"/api/documents/{req}/versions"))
    assert versions[0]["source_filename"] == "（画面で編集）" and versions[0]["label"] == "画面で修正"
    d = ok(client.get(f"/api/diff?from={versions[1]['id']}&to={versions[0]['id']}"))
    assert [i["item_id"] for i in d["added"]] == ["REQ-004"]
    assert {i["item_id"] for i in d["changed"]} == {"REQ-001", "REQ-002", "REQ-003"}


def test_edit_overwrite_keeps_version_no_and_marks_links_suspect(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)
    base = latest(client, req)

    def mutate(schema, rows):
        rows[0]["data"]["rname"] = "ログイン（上書き）"

    r = ok(edit(client, req, base, "overwrite", mutate))
    assert r["version_id"] == base["version_id"] and r["version_no"] == 1
    assert len(ok(client.get(f"/api/documents/{req}/versions"))) == 1
    after = latest(client, req)
    assert after["items"][0]["data"]["rname"] == "ログイン（上書き）"
    # 上位の内容が変わったので、REQ-001 へのリンクは要確認になる
    ev = ok(client.get(f"/api/trace/{rel}"))
    suspect = {(l["upper_item_id"], l["lower_item_id"]) for l in ev["suspect"]}
    assert ("REQ-001", "SCR-01") in suspect
    # 元の取り込みの設定は残る
    v = ok(client.get(f"/api/documents/{req}/versions"))[0]
    assert v["import_settings"]["format"] == "csv" and "edited_at" in v["import_settings"]


def test_edit_validation(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    base = latest(client, req)

    def dup(schema, rows):
        rows.append({"data": {"rid": "REQ-001"}})
        rows.append({"data": {"rname": "ID なし"}})

    r = edit(client, req, base, "new", dup)
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "4 行目: ID「REQ-001」が重複しています" in msg and "5 行目: ID が空です" in msg

    # 型に合わない値は警告のセルとして保存する（取り込みと同じ）
    def bad(schema, rows):
        rows[0]["data"]["rpri"] = "未定義"

    ok(edit(client, req, base, "overwrite", bad))
    assert latest(client, req)["items"][0]["invalid"] == ["rpri"]

    assert edit(client, req, base, "replace").status_code == 400


def test_edit_conflict_when_version_changed(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    base = latest(client, req)
    do_import(client, req, "req.csv", req_csv("変更"))
    r = edit(client, req, base, "new")
    assert r.status_code == 400 and r.json()["error"]["code"] == "version_conflict"


def test_edit_list_values(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)
    base = latest(client, scr)
    ref_key = [c for c in base["schema"]["columns"] if c.get("ref_document_id")][0]["key"]

    def mutate(schema, rows):
        rows[2]["data"][ref_key] = ["REQ-003", " ", "REQ-001"]  # 空の要素は捨てる

    ok(edit(client, scr, base, "new", mutate))
    after = {i["item_id"]: i for i in latest(client, scr)["items"]}
    assert after["SCR-03"]["data"][ref_key] == ["REQ-003", "REQ-001"]
    # 参照 ID 列を編集すると自動リンクも作り直される
    pairs = {(l["upper_item_id"], l["lower_item_id"]) for l in ok(client.get(f"/api/trace/{rel}"))["links"]}
    assert ("REQ-003", "SCR-03") in pairs and ("REQ-001", "SCR-03") in pairs


def test_choice_filters(client):
    req, scr, rel = setup(client)
    vid = do_import(client, req, "req.csv", req_csv())["version_id"]

    def ids(**params):
        return [i["item_id"] for i in ok(client.get(f"/api/versions/{vid}/items", params=params))["items"]]

    # REQ-001 高 ○ / REQ-002 中 × / REQ-003 最高（選択肢外） Yes
    assert ids(**{"m.rpri": ["高", "中"]}) == ["REQ-001", "REQ-002"]
    assert ids(**{"m.rpri": "__other__"}) == ["REQ-003"]
    assert ids(**{"m.rmust": "true"}) == ["REQ-001", "REQ-003"]
    assert ids(**{"m.rmust": "false", "m.rpri": "中"}) == ["REQ-002"]
    assert ids(**{"m.rnote": "__empty__"}) == ["REQ-001", "REQ-002", "REQ-003"]  # string 列は対象外
    # bool・enum の空欄
    base = latest(client, req)

    def blank(schema, rows):
        rows[1]["data"]["rmust"] = None

    ok(edit(client, req, base, "overwrite", blank))
    assert ids(**{"m.rmust": "__empty__"}) == ["REQ-002"]


# --- ID の付け直し ------------------------------------------------------------------


def edit_with_orig(client, doc, base, mutate, mode="new"):
    rows = [{"orig_id": i["item_id"], "data": dict(i["data"])} for i in base["items"]]
    mutate(rows)
    return client.post(
        f"/api/documents/{doc}/edit",
        json={"base_version_id": base["version_id"], "mode": mode, "schema": base["schema"], "items": rows},
    )


def test_rename_id_updates_links_and_references(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)  # SCR-01 → REQ-001;REQ-002、SCR-02 → REQ-002
    # 手動リンクも付け直されることを確かめる
    ok(client.post("/api/links", json={"relation_id": rel, "upper_item_id": "REQ-002", "lower_item_id": "SCR-03"}))
    base = latest(client, req)
    renames = {"REQ-002": "REQ-020"}

    impact = ok(client.post(f"/api/documents/{req}/rename-impact", json={"renames": renames}))
    assert impact["links"] == [{"document": "画面定義書", "count": 3}]
    assert impact["documents"][0]["document"] == "画面定義書"
    assert impact["documents"][0]["items"] == ["SCR-01", "SCR-02"]

    def mutate(rows):
        rows[1]["data"]["rid"] = "REQ-020"

    r = ok(edit_with_orig(client, req, base, mutate))
    assert r["renamed"] == 1
    # リンクは新しい ID に付け替わり、ID を変えただけなので要確認にもリンク切れにもならない
    ev = ok(client.get(f"/api/trace/{rel}"))
    pairs = {(l["upper_item_id"], l["lower_item_id"]) for l in ev["links"]}
    assert ("REQ-020", "SCR-01") in pairs and ("REQ-020", "SCR-02") in pairs and ("REQ-020", "SCR-03") in pairs
    assert not any("REQ-002" in p for p in pairs)
    assert ev["suspect"] == [] and not any(l["upper_item_id"] == "REQ-020" for l in ev["broken"])
    # 下位文書の参照 ID 列も書き換わる（版は増えない）
    scr_items = {i["item_id"]: i for i in latest(client, scr)["items"]}
    ref_key = [c for c in latest(client, scr)["schema"]["columns"] if c.get("ref_document_id")][0]["key"]
    assert scr_items["SCR-01"]["data"][ref_key] == ["REQ-001", "REQ-020"]
    assert scr_items["SCR-02"]["data"][ref_key] == ["REQ-020"]
    assert len(ok(client.get(f"/api/documents/{scr}/versions"))) == 1
    # 手動リンクは手動のまま
    manual = [l for l in ev["links"] if l["lower_item_id"] == "SCR-03"][0]
    assert manual["origin"] == "manual"


def test_rename_with_other_changes_is_suspect(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)
    base = latest(client, req)

    def mutate(rows):
        rows[0]["data"]["rid"] = "REQ-100"
        rows[0]["data"]["rname"] = "ログイン（改）"

    ok(edit_with_orig(client, req, base, mutate, mode="overwrite"))
    ev = ok(client.get(f"/api/trace/{rel}"))
    assert {(l["upper_item_id"], l["lower_item_id"]) for l in ev["suspect"]} == {("REQ-100", "SCR-01")}


def test_rename_rejects_existing_id(client):
    req, scr, rel = setup(client)
    do_import(client, req, "req.csv", req_csv())
    base = latest(client, req)

    def swap(rows):
        rows[0]["data"]["rid"] = "REQ-002"
        rows[1]["data"]["rid"] = "REQ-001"

    r = edit_with_orig(client, req, base, swap)
    assert r.status_code == 400 and "別の項目で使われている" in r.json()["error"]["message"]

    def reuse_deleted(rows):
        rows[0]["data"]["rid"] = "REQ-003"
        del rows[2]

    assert edit_with_orig(client, req, base, reuse_deleted).status_code == 400
