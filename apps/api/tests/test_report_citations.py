"""正文里的 [3] 必须指回真正的那一条资料。

简报的全部可信度来自「每句话都挂着编号」这条规则。但编号只有在**能验证**时
才起作用——原来 [3] 只是三个字符，引用清单在页面底部另起一块，想核对得自己
数到第三条。数一次还行，一份简报十几个编号，没人会去数。
**能验证但很费劲，等于不能验证。**

所以这里测的是编号这条链上唯一会断的地方：序号是谁定的。
"""

import asyncio

import pytest

from stock_decision import chain_and_reports, repository
from stock_decision.schemas import CompanyInput, EvidenceCreate, EvidencePolarity

from tests.test_api import request


def _company_with_evidence(count: int = 3) -> int:
    company = repository.create_company(
        CompanyInput(symbol="600519", name="贵州茅台", industry="白酒"))
    for index in range(count):
        repository.create_evidence(company["id"], EvidenceCreate(
            source_name=f"公告{index}",
            source_url=f"http://example.test/{index}",
            excerpt=f"第 {index} 条资料的正文",
            polarity=EvidencePolarity.neutral,
            occurred_at=f"2026-0{index + 1}-01T00:00:00",
        ))
    return company["id"]


def _fake_model(monkeypatch, payload: str) -> None:
    monkeypatch.setattr(chain_and_reports, "_call_model", lambda *a, **k: payload)


def test_citations_carry_a_way_to_open_the_source(monkeypatch) -> None:
    """每条引用都要带 ref 和能点开的东西，否则角标点了没地方去。"""
    company_id = _company_with_evidence()
    _fake_model(monkeypatch, """{"title": "简报", "business": ["主营白酒 [1]"],
      "changes": [], "implications": [], "citations": [], "unknowns": []}""")

    report = repository.generate_report(company_id)

    assert report["citations"], "引用清单是空的，正文里的编号就无处可去"
    first = report["citations"][0]
    assert first["ref"] == 1
    assert first["evidence_id"] is not None
    assert first["url"].startswith("http")


def test_the_numbering_is_ours_not_the_models(monkeypatch) -> None:
    """模型自己回的 citations 要被覆盖掉。

    模型给的 label 是它复述的，点不开任何东西。序号由我们在送进去之前定死，
    回来照序号查表——中间不能有「模型说的 3 是哪个 3」这种猜测。
    """
    company_id = _company_with_evidence()
    _fake_model(monkeypatch, """{"title": "简报", "business": ["随便 [1]"],
      "changes": [], "implications": [],
      "citations": [{"ref": 1, "label": "模型自己编的来源，点不开"}], "unknowns": []}""")

    report = repository.generate_report(company_id)

    labels = [c["label"] for c in report["citations"]]
    assert "模型自己编的来源，点不开" not in labels


def test_the_prompt_and_the_table_use_the_same_numbers(monkeypatch) -> None:
    """送给模型的编号，和回来查表用的编号，必须是同一套。

    两处各 enumerate 一次的话，只要中间筛掉过一条，正文里的 [3] 就会指到
    另一条资料上——而这种错完全看不出来：编号仍然在，指向的东西是错的。
    """
    company_id = _company_with_evidence(count=3)
    seen: dict[str, str] = {}

    def capture(system, user, *args, **kwargs):
        seen["prompt"] = user
        return """{"title": "简报", "business": ["a [2]"], "changes": [],
                   "implications": [], "citations": [], "unknowns": []}"""

    monkeypatch.setattr(chain_and_reports, "_call_model", capture)
    report = repository.generate_report(company_id)

    # 提示词里 [2] 对应的那条资料，跟引用表里 ref=2 的那条，得是同一条
    line = next(l for l in seen["prompt"].splitlines() if l.startswith("[2]"))
    ref_two = next(c for c in report["citations"] if c["ref"] == 2)
    assert ref_two["label"] in line


def test_the_api_hands_back_the_citation_details(monkeypatch) -> None:
    """走一趟 HTTP —— 响应模型丢字段的坑今天已经踩过两次。"""
    company_id = _company_with_evidence()
    _fake_model(monkeypatch, """{"title": "简报", "business": ["主营白酒 [1]"],
      "changes": [], "implications": [], "citations": [], "unknowns": []}""")
    repository.generate_report(company_id)

    listed = asyncio.run(request("GET", "/api/v1/reports")).json()

    first = listed[0]["citations"][0]
    assert first["ref"] == 1 and first["url"].startswith("http")
