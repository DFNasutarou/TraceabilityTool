"""トレースの評価（未トレース・リンク切れ・要確認・網羅率）。各文書の最新版を対象にする。"""

from __future__ import annotations

import sqlite3

from . import links as link_svc
from . import relations as rel_svc
from . import versions as ver_svc

STATUS_OK = "ok"
STATUS_SUSPECT = "suspect"
STATUS_BROKEN = "broken"


def link_origin(link: dict) -> str:
    if link["manual"]:
        return "manual"
    return "auto"


def link_status(link: dict, upper_hashes: dict[str, str], lower_hashes: dict[str, str]) -> str:
    up = upper_hashes.get(link["upper_item_id"])
    lo = lower_hashes.get(link["lower_item_id"])
    if up is None or lo is None:
        return STATUS_BROKEN
    if up != link["upper_hash_ack"] or lo != link["lower_hash_ack"]:
        return STATUS_SUSPECT
    return STATUS_OK


def _evaluate(conn: sqlite3.Connection, rel: dict) -> dict:
    """関係 1 つ分の評価。書き込みが起きるまで結果をキャッシュする（書き換えないこと）。"""
    cache = getattr(conn, "cache", None)
    key = ("rel", rel["id"])
    if cache is not None and key in cache["eval"]:
        return cache["eval"][key]
    result = _evaluate_uncached(conn, rel)
    if cache is not None:
        cache["eval"][key] = result
    return result


def _evaluate_uncached(conn: sqlite3.Connection, rel: dict) -> dict:
    upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
    lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
    links = []
    upper_linked: set[str] = set()
    lower_linked: set[str] = set()
    for link in link_svc.links_of_relation(conn, rel["id"], active_only=True):
        status = link_status(link, upper_hashes, lower_hashes)
        links.append(
            {
                "id": link["id"],
                "upper_item_id": link["upper_item_id"],
                "lower_item_id": link["lower_item_id"],
                "origin": link_origin(link),
                "status": status,
            }
        )
        if status != STATUS_BROKEN:
            upper_linked.add(link["upper_item_id"])
            lower_linked.add(link["lower_item_id"])
    return {
        "relation": rel,
        "upper_hashes": upper_hashes,
        "lower_hashes": lower_hashes,
        "links": links,
        "upper_linked": upper_linked,
        "lower_linked": lower_linked,
    }


def _side(conn: sqlite3.Connection, doc_id: int, linked: set[str]) -> dict:
    v = ver_svc.latest_version(conn, doc_id)
    order = [i["item_id"] for i in ver_svc.load_items(conn, v["id"])] if v else []
    untraced = [i for i in order if i not in linked]
    total = len(order)
    return {
        "doc_id": doc_id,
        "version_id": v["id"] if v else None,
        "total": total,
        "untraced": untraced,
        "coverage": (total - len(untraced)) / total if total else None,
    }


def evaluate_relation(conn: sqlite3.Connection, rel_id: int) -> dict:
    """関係 1 つ分の評価結果。

    upper.untraced: 下位へのリンクが無い上位項目
    lower.untraced: 上位へのリンクが無い下位項目
    """
    rel = rel_svc.get_relation(conn, rel_id)
    ev = _evaluate(conn, rel)
    return {
        "relation": rel,
        "upper": _side(conn, rel["upper_doc_id"], ev["upper_linked"]),
        "lower": _side(conn, rel["lower_doc_id"], ev["lower_linked"]),
        "links": ev["links"],
        "broken": [l for l in ev["links"] if l["status"] == STATUS_BROKEN],
        "suspect": [l for l in ev["links"] if l["status"] == STATUS_SUSPECT],
    }


def relation_summary(conn: sqlite3.Connection, rel_id: int) -> dict:
    ev = evaluate_relation(conn, rel_id)
    return {
        "relation": ev["relation"],
        "upper_total": ev["upper"]["total"],
        "upper_untraced": len(ev["upper"]["untraced"]),
        "upper_coverage": ev["upper"]["coverage"],
        "lower_total": ev["lower"]["total"],
        "lower_untraced": len(ev["lower"]["untraced"]),
        "lower_coverage": ev["lower"]["coverage"],
        "broken": len(ev["broken"]),
        "suspect": len(ev["suspect"]),
        "links": len(ev["links"]),
    }


def item_trace_summary(conn: sqlite3.Connection, doc_id: int) -> dict[str, dict]:
    """文書の最新版の項目ごとのトレース状態。

    no_upper: 上位文書があるのに、いずれかの関係で上位へのリンクが無い
    no_lower: 下位文書があるのに、いずれかの関係で下位へのリンクが無い
    結果はキャッシュを共有するので書き換えないこと。
    """
    cache = getattr(conn, "cache", None)
    key = ("doc", doc_id)
    if cache is not None and key in cache["eval"]:
        return cache["eval"][key]
    hashes = ver_svc.latest_hashes(conn, doc_id)
    summary = {
        i: {"upper_count": 0, "lower_count": 0, "no_upper": False, "no_lower": False, "suspect": 0, "broken": 0}
        for i in hashes
    }
    for rel in rel_svc.relations_of(conn, doc_id):
        ev = _evaluate(conn, rel)
        as_upper = rel["upper_doc_id"] == doc_id
        mine = "upper_item_id" if as_upper else "lower_item_id"
        linked = ev["upper_linked"] if as_upper else ev["lower_linked"]
        count_key = "lower_count" if as_upper else "upper_count"
        flag_key = "no_lower" if as_upper else "no_upper"
        for item_id, s in summary.items():
            if item_id not in linked:
                s[flag_key] = True
        for link in ev["links"]:
            s = summary.get(link[mine])
            if s is None:
                continue
            if link["status"] == STATUS_BROKEN:
                s["broken"] += 1
                continue
            s[count_key] += 1
            if link["status"] == STATUS_SUSPECT:
                s["suspect"] += 1
    if cache is not None:
        cache["eval"][key] = summary
    return summary


def document_summary(conn: sqlite3.Connection, doc_id: int) -> dict:
    s = item_trace_summary(conn, doc_id)
    return {
        "no_upper": sum(1 for v in s.values() if v["no_upper"]),
        "no_lower": sum(1 for v in s.values() if v["no_lower"]),
        "suspect_items": sum(1 for v in s.values() if v["suspect"]),
        "broken_items": sum(1 for v in s.values() if v["broken"]),
    }
