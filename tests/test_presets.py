"""横並び表示の表示設定のプリセット。"""

from .test_flow import ok


def test_presets(client):
    doc = ok(client.post("/api/documents", json={"name": "画面"}))["id"]
    url = f"/api/documents/{doc}/presets"
    a = ok(client.post(url, json={"name": "画面遷移だけ", "settings": {"hidden": ["1:upper", "bad"], "min_importance": "mid"}, "is_default": True}))["id"]
    b = ok(client.post(url, json={"name": "すべて", "settings": {}}))["id"]
    ps = ok(client.get(url))
    assert [(p["name"], p["is_default"]) for p in ps] == [("すべて", False), ("画面遷移だけ", True)]
    assert ps[1]["settings"] == {"hidden": ["1:upper"], "min_importance": "mid", "wrap": True}
    # 既定は文書ごとに 1 つ
    ok(client.put(f"/api/presets/{b}", json={"is_default": True}))
    assert {p["id"]: p["is_default"] for p in ok(client.get(url))} == {a: False, b: True}
    # 名前の重複・空はエラー
    assert client.post(url, json={"name": "すべて"}).status_code == 400
    assert client.put(f"/api/presets/{a}", json={"name": " "}).status_code == 400
    ok(client.put(f"/api/presets/{a}", json={"name": "遷移", "settings": {"hidden": [], "wrap": False}}))
    assert [p for p in ok(client.get(url)) if p["id"] == a][0]["settings"] == {"hidden": [], "min_importance": "low", "wrap": False}
    ok(client.delete(f"/api/presets/{a}"))
    assert [p["id"] for p in ok(client.get(url))] == [b]
    # 文書を消すとプリセットも消える
    ok(client.delete(f"/api/documents/{doc}"))
    assert client.put(f"/api/presets/{b}", json={"name": "x"}).status_code == 404
