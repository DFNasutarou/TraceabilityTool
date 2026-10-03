from tracetool import colschema


def col(type_, **kw):
    c = {"key": "k", "name": "n", "type": type_}
    c.update(kw)
    return colschema.normalize_schema({"columns": [c]})["columns"][0]


def test_int_normalization():
    c = col("int")
    assert colschema.normalize_cell(c, " 12 ") == (12, False)
    assert colschema.normalize_cell(c, "１，２３４") == (1234, False)
    assert colschema.normalize_cell(c, "3.0") == (3, False)
    assert colschema.normalize_cell(c, "abc") == ("abc", True)
    assert colschema.normalize_cell(c, "") == (None, False)


def test_bool_default_values():
    c = col("bool")
    assert colschema.normalize_cell(c, "○") == (True, False)
    assert colschema.normalize_cell(c, "×") == (False, False)
    assert colschema.normalize_cell(c, "yes") == (True, False)
    assert colschema.normalize_cell(c, "ＮＯ") == (False, False)
    assert colschema.normalize_cell(c, "たぶん") == ("たぶん", True)


def test_bool_custom_values():
    c = col("bool", bool_values={"true": ["済"], "false": ["未"]})
    assert colschema.normalize_cell(c, "済") == (True, False)
    assert colschema.normalize_cell(c, "○") == ("○", True)


def test_enum_and_list():
    c = col("enum", enum_values=["高", "中", "低"], list={"delimiters": ["/"]})
    assert colschema.normalize_cell(c, "高 / 低") == (["高", "低"], False)
    assert colschema.normalize_cell(c, "高/特高") == (["高", "特高"], True)


def test_list_with_multiple_delimiters_and_newline():
    c = col("string", list={"delimiters": [";", "\\n"]})
    assert colschema.normalize_cell(c, "A;B\nC;;") == (["A", "B", "C"], False)


def test_hash_ignores_null_and_key_order():
    assert colschema.content_hash({"a": 1, "b": "x"}) == colschema.content_hash({"b": "x", "a": 1, "c": None})
    assert colschema.content_hash({"a": 1}) != colschema.content_hash({"a": 2})


def test_validate_schema():
    errs = colschema.validate_schema(colschema.normalize_schema({"columns": [{"name": "a", "type": "string"}]}))
    assert any("ID 型" in e for e in errs)
    errs = colschema.validate_schema(
        colschema.normalize_schema(
            {"columns": [{"name": "id", "type": "id"}, {"name": "b", "type": "bool", "bool_values": {"true": ["1"], "false": ["1"]}}]}
        )
    )
    assert any("同じ文字列" in e for e in errs)
