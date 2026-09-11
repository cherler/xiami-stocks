"""投资逻辑要能删，而且删了不带走证据。

**之前只能加不能减。** 模型起草必然会产生一些不满意的版本，没有删除就只能标成
「已破坏」压在列表里——而那个状态本来的意思是「事实推翻了它」，不是「我不要这条」。
两件事混在一起，列表很快就没法看。
"""

import pytest

from stock_decision import access, repository
from stock_decision.schemas import CompanyInput, EvidenceCreate, ThesisCreate


@pytest.fixture()
def company():
    return repository.create_company(
        CompanyInput(symbol="600519", name="贵州茅台", industry="白酒"))


def test_a_thesis_can_be_deleted(company):
    thesis = repository.create_thesis(company["id"], ThesisCreate(claim="不满意的判断"))
    assert repository.delete_thesis(thesis["id"]) is True
    assert repository.get_company(company["id"])["theses"] == []


def test_deleting_a_thesis_keeps_its_evidence(company):
    """证据是已经发生的事实，不因为某条判断被丢掉而失效。"""
    thesis = repository.create_thesis(company["id"], ThesisCreate(claim="要删掉的判断"))
    repository.create_evidence(company["id"], EvidenceCreate(
        source_name="2025 年报", excerpt="经营现金流 615 亿", polarity="support",
        occurred_at="2026-03-31", thesis_id=thesis["id"]))

    repository.delete_thesis(thesis["id"])
    detail = repository.get_company(company["id"])
    assert len(detail["evidences"]) == 1, "证据跟着判断一起没了"


def test_deleting_someone_elses_thesis_does_nothing(company):
    thesis = repository.create_thesis(company["id"], ThesisCreate(claim="站主的判断"))

    token = access.set_scope("user-7")
    try:
        assert repository.delete_thesis(thesis["id"]) is False
    finally:
        access.reset_scope(token)

    assert len(repository.get_company(company["id"])["theses"]) == 1


def test_deleting_a_missing_thesis_reports_false():
    assert repository.delete_thesis(999999) is False
