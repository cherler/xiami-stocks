"""数据隔离：站主的存量数据只有站主可见，其他用户各看各的。

这些测试直接操纵数据域（contextvar），不经过 HTTP——HTTP 层的身份解析
（Cookie → 主站 /v1/me → 域）在 access.check 里，单独由三档实测覆盖
（游客 401 / 站主 200 / 陌生登录用户各看各的）。
"""

import pytest

from stock_decision import access, repository
from stock_decision.schemas import (
    CompanyInput,
    EvidenceCreate,
    PortfolioCreate,
    ThesisCreate,
    TradeCreate,
    TradeSide,
)


@pytest.fixture()
def as_user():
    """在指定数据域里执行。用完自动复位到默认（站主域）。"""
    tokens = []

    def enter(scope):
        tokens.append(access.set_scope(scope))

    yield enter
    while tokens:
        access.reset_scope(tokens.pop())


def test_两个用户的公司档案互相看不见(as_user):
    as_user("u_alice000000000000000000")
    alice_co = repository.create_company(CompanyInput(
        symbol="600519", name="贵州茅台", industry="白酒"))
    assert repository.get_company(alice_co["id"]) is not None

    as_user("u_bob00000000000000000000")
    assert repository.list_companies() == []
    # 按 id 直接摸也摸不到——隔离必须挡住 id 枚举，不只是列表页
    assert repository.get_company(alice_co["id"]) is None
    # 同一个代码两个人都能建：唯一约束是按用户的
    bob_co = repository.create_company(CompanyInput(
        symbol="600519", name="贵州茅台", industry="白酒"))
    assert bob_co["id"] != alice_co["id"]
    assert len(repository.list_companies()) == 1


def test_子表通过公司归属继承隔离(as_user):
    as_user("u_alice000000000000000000")
    company = repository.create_company(CompanyInput(
        symbol="000333", name="美的集团", industry="家电"))
    thesis = repository.create_thesis(company["id"], ThesisCreate(claim="白电龙头，赌的是全球化产能"))
    assert thesis is not None

    as_user("u_bob00000000000000000000")
    # Bob 往 Alice 的公司里塞证据：公司在他的域里不存在，直接 None
    assert repository.create_evidence(company["id"], EvidenceCreate(
        source_name="x", excerpt="试图跨域写入")) is None
    assert repository.thesis_review_context(thesis["id"]) is None


def test_持仓账本按域隔离且组合名可以重名(as_user):
    as_user("u_alice000000000000000000")
    company = repository.create_company(CompanyInput(symbol="601318", name="中国平安", industry="保险"))
    portfolio = repository.create_portfolio(PortfolioCreate(name="主组合"))
    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company["id"], side=TradeSide.buy, weight_percent=20, rationale="建仓测试"))
    assert repository.get_portfolio(portfolio["id"])["trade_count"] == 1

    as_user("u_bob00000000000000000000")
    assert repository.get_portfolio(portfolio["id"]) is None       # 直接摸 id 摸不到
    mine = repository.create_portfolio(PortfolioCreate(name="主组合"))  # 重名不冲突
    assert mine["id"] != portfolio["id"]
    assert [p["name"] for p in repository.list_portfolios()].count("主组合") >= 1
    # Bob 的账本里没有任何交易
    assert all(p["trade_count"] == 0 for p in repository.list_portfolios())


def test_规则词表各学各的(as_user):
    as_user("u_alice000000000000000000")
    repository.save_rule_term("注销到期未行权", "高", "激励执行")
    assert len(repository.list_rule_terms()) == 1

    as_user("u_bob00000000000000000000")
    assert repository.list_rule_terms() == []                      # 看不到别人的词
    repository.save_rule_term("注销到期未行权", "低", "自定义")      # 同一个词可以有相反判断
    assert repository.list_rule_terms()[0]["relevance"] == "低"


def test_站主域看得到存量数据其他人看不到(as_user):
    # 默认（站主域）建一条——模拟建库以来的存量数据
    legacy = repository.create_company(CompanyInput(symbol="600036", name="招商银行", industry="银行"))
    assert repository.get_company(legacy["id"]) is not None

    as_user("u_visitor0000000000000000")
    assert repository.get_company(legacy["id"]) is None
    assert repository.dashboard()["total_theses"] == 0

    as_user(access.OWNER_SCOPE)                                    # 管理员登录 → 落回站主域
    assert repository.get_company(legacy["id"]) is not None


def test_系统域不过滤_调度器要替所有人同步(as_user):
    as_user("u_alice000000000000000000")
    repository.create_company(CompanyInput(symbol="300750", name="宁德时代", industry="电池"))

    as_user(None)                                                  # 调度器的系统域
    symbols = {row["symbol"] for row in repository.list_companies()}
    assert "300750" in symbols                                     # 看得到所有域的公司
