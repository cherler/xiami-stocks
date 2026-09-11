"""研究简报出来是什么形状。

原来它出来是一坨 markdown，页面 `<pre>` 一贴就完事——四节标题、每条陈述后面的
`[3]` 编号，全靠人自己在等宽字里认。模型明明是按四节写的，结构在落库前就被拼没了。

现在三节各存一个短句数组。两件事必须同时成立，缺一个就白改：

1. 模型没按数组给（写成一整段）时，不能整节丢掉；
2. `body` 由三节拼出来，而不是反过来。**拼平的方向只能有一个**——否则页面显示的
   和导出的迟早会是两份不一样的简报，而这种不一致没人会发现。
"""

import asyncio

from stock_decision import chain_and_reports, repository


def _fake_model(monkeypatch, payload: str) -> None:
    monkeypatch.setattr(chain_and_reports, "_call_model", lambda *a, **k: payload)


COMPANY = {"name": "贵州茅台", "symbol": "600519", "industry": "白酒"}
SOURCES = [{"label": "2025年年报 · 2026-03-28", "text": "营业收入同比增长 12%"}]


def test_sections_come_back_as_lists(monkeypatch) -> None:
    _fake_model(monkeypatch, """{"title": "茅台简报",
      "business": ["主营白酒 [1]", "以直销为主 [1]"],
      "changes": ["收入同比增长 12% [1]"],
      "implications": ["增速放缓但仍为正 [1]"],
      "citations": [{"ref": 1, "label": "2025年年报"}],
      "unknowns": ["渠道库存没有披露"]}""")

    report = chain_and_reports.write_report(COMPANY, SOURCES)

    assert report["business"] == ["主营白酒 [1]", "以直销为主 [1]"]
    assert report["changes"] == ["收入同比增长 12% [1]"]
    assert report["implications"] == ["增速放缓但仍为正 [1]"]


def test_body_is_derived_from_the_sections(monkeypatch) -> None:
    """body 是拼出来的，三节是源头——两边不能各写各的。"""
    _fake_model(monkeypatch, """{"title": "茅台简报",
      "business": ["主营白酒 [1]"], "changes": ["收入增长 [1]"], "implications": ["还在增长 [1]"],
      "body": "这是模型自己写的另一份正文，不该被采用",
      "citations": [], "unknowns": []}""")

    report = chain_and_reports.write_report(COMPANY, SOURCES)

    assert "这是模型自己写的另一份正文" not in report["body"]
    assert "主营白酒 [1]" in report["body"]
    assert "## 这家公司在做什么" in report["body"]


def test_a_section_written_as_one_paragraph_is_not_lost(monkeypatch) -> None:
    """模型偶尔会把一节写成整段。按行拆开，别整节丢掉。"""
    _fake_model(monkeypatch, """{"title": "简报",
      "business": "主营白酒 [1]\\n以直销为主 [1]",
      "changes": [], "implications": [], "citations": [], "unknowns": []}""")

    report = chain_and_reports.write_report(COMPANY, SOURCES)

    assert report["business"] == ["主营白酒 [1]", "以直销为主 [1]"]


def test_an_old_style_reply_still_yields_a_readable_body(monkeypatch) -> None:
    """只给了 body、没给三节的回复，body 要原样保留——不然整份简报变成空白。"""
    _fake_model(monkeypatch, """{"title": "简报", "body": "## 这家公司在做什么\\n主营白酒 [1]",
      "citations": [], "unknowns": []}""")

    report = chain_and_reports.write_report(COMPANY, SOURCES)

    assert report["business"] == []
    assert "主营白酒 [1]" in report["body"]


def test_the_api_hands_back_the_sections(monkeypatch) -> None:
    """走一趟 HTTP。响应模型没声明的字段会被静默丢掉——候选初筛就是这么白屏的。"""
    from tests.test_api import request

    company = asyncio.run(request("POST", "/api/v1/companies",
                                  {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"})).json()
    _fake_model(monkeypatch, """{"title": "茅台简报",
      "business": ["主营白酒 [1]"], "changes": ["收入增长 [1]"], "implications": ["还在增长 [1]"],
      "citations": [], "unknowns": []}""")
    monkeypatch.setattr(repository, "write_report",
                        lambda c, s: chain_and_reports.write_report(c, s or SOURCES))
    repository.generate_report(company["id"])

    listed = asyncio.run(request("GET", "/api/v1/reports")).json()

    assert listed[0]["business"] == ["主营白酒 [1]"]
    assert listed[0]["changes"] == ["收入增长 [1]"]
    assert listed[0]["implications"] == ["还在增长 [1]"]
