"""产业链关系的手动增删，以及报告的删除。

用户报的是「无法新增、无法删除」。查下来是两回事：
· 删除**功能一直在**，是我做成图之后把按钮挪进了"点了才出现的详情卡"——
  操作从页面上消失了。列表天然把每行的操作摆在那里，图没有这个便利。
· 新增确实没有。模型给的往往不全（实测工商银行的上游只给出「中央银行」一条），
  而你自己知道的没地方录，这一页就只能被动接受模型给什么看什么。
"""

import asyncio

import pytest

from stock_decision import repository
from stock_decision.schemas import CompanyInput

from tests.test_api import request


def _company() -> int:
    return repository.create_company(
        CompanyInput(symbol="601398", name="工商银行", industry="银行"))["id"]


def test_a_hand_written_link_counts_as_confirmed():
    """手写的直接算已证实——**是你自己填的，没有"待你核对"这回事**。

    模型推断的才需要核对，那是两种东西。
    """
    company_id = _company()

    view = repository.add_supply_chain_link(company_id, {
        "relation": "上游供应", "counterpart": "同业拆借市场", "detail": "短期资金来源"})

    assert len(view["links"]) == 1
    assert view["links"][0]["confidence"] == "已证实"
    assert view["confirmed"] == 1


def test_an_unknown_relation_is_refused():
    """关系只有四种。放行别的会在图上多出一组谁也不知道该画在哪的节点。"""
    company_id = _company()

    assert repository.add_supply_chain_link(
        company_id, {"relation": "瞎写", "counterpart": "某某"}) is None
    assert repository.add_supply_chain_link(
        company_id, {"relation": "上游供应", "counterpart": "  "}) is None


def test_the_api_refuses_it_with_422():
    company_id = _company()

    response = asyncio.run(request("POST", f"/api/v1/companies/{company_id}/supply-chain",
                                   {"relation": "瞎写", "counterpart": "某某"}))

    assert response.status_code == 422


def test_a_link_can_be_deleted():
    company_id = _company()
    repository.add_supply_chain_link(company_id, {"relation": "同业对手", "counterpart": "建设银行"})
    link_id = repository.get_supply_chain(company_id)["links"][0]["id"]

    assert repository.delete_supply_chain_link(link_id) is True
    assert repository.get_supply_chain(company_id)["links"] == []


def test_a_link_on_someone_elses_company_is_not_created():
    """别人的公司 id 试出来也加不进去。"""
    assert repository.add_supply_chain_link(999999, {
        "relation": "上游供应", "counterpart": "某某"}) is None


def test_deleting_a_report_is_scoped_to_your_own_companies(monkeypatch):
    """只按 id 删的话，换个 id 就能删掉别人的报告，而且删了不留痕。"""
    company_id = _company()
    from stock_decision import chain_and_reports
    monkeypatch.setattr(chain_and_reports, "_call_model", lambda *a, **k:
                        '{"title": "简报", "business": ["a [1]"], "changes": [],'
                        ' "implications": [], "citations": [], "unknowns": []}')
    from stock_decision.schemas import EvidenceCreate, EvidencePolarity
    repository.create_evidence(company_id, EvidenceCreate(
        source_name="公告", excerpt="这是一段够长的正文", polarity=EvidencePolarity.neutral))
    report = repository.generate_report(company_id)

    assert repository.delete_report(report["id"]) is True
    assert repository.delete_report(report["id"]) is False       # 删过就没了
    assert repository.delete_report(999999) is False


def test_the_delete_endpoint_reports_what_happened():
    response = asyncio.run(request("DELETE", "/api/v1/reports/999999"))

    assert response.status_code == 200
    assert response.json() == {"deleted": False}
