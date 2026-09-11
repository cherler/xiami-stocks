"""资金流：先看本地快照，拉不到就给上一份——不要整块 503。

## 原来怎么坏的

`market_fund_flow_view()` 每次请求都直接拉供应商。冷启动、对方抖一下、
网络慢一点，驾驶舱那一屏就是 503——**而这组数一个交易日只变一次**。
把一屏日更数据的可用性绑在第三方的实时可达性上，不划算。

所以这里测三件事：拉到了要存下来、没过期就不再去拉、拉不到要降级而不是报错。
"""

import pytest

from stock_decision import repository
from stock_decision.market_data import MarketDataError

_ROWS = [
    {"date": "2026-08-11", "mainNetInflow": -1.2e10, "mainNetInflowPercent": -1.5,
     "superLargeNetInflow": -3e9, "largeNetInflow": -9e9, "mediumNetInflow": 4e9,
     "smallNetInflow": 8e9, "shClose": 3400.5, "shChangePercent": -0.4,
     "szClose": 10500.2, "szChangePercent": -0.6},
    {"date": "2026-08-12", "mainNetInflow": 5.5e9, "mainNetInflowPercent": 0.7,
     "superLargeNetInflow": 2e9, "largeNetInflow": 3.5e9, "mediumNetInflow": -1e9,
     "smallNetInflow": -4.5e9, "shClose": 3421.0, "shChangePercent": 0.6,
     "szClose": 10588.0, "szChangePercent": 0.8},
]


def test_拉回来的会存进本地快照(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "_fetch_market_fund_flow", lambda: _ROWS)
    view = repository.market_fund_flow_view()
    assert [p["date"] for p in view["points"]] == ["2026-08-11", "2026-08-12"], "画图要按时间正序"
    assert view["degraded"] is False and view["synced_at"]
    assert view["as_of"] == "2026-08-12"


def test_没过期就不再去拉供应商(monkeypatch: pytest.MonkeyPatch) -> None:
    """**这才是这次改动省下的东西**：每次点开驾驶舱都打一次外部接口。"""
    monkeypatch.setattr(repository, "_fetch_market_fund_flow", lambda: _ROWS)
    repository.market_fund_flow_view()

    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise AssertionError("不该再拉一次")

    monkeypatch.setattr(repository, "_fetch_market_fund_flow", _boom)
    view = repository.market_fund_flow_view()
    assert calls["n"] == 0
    assert len(view["points"]) == 2


def test_拉不到时给上一份并且说明白(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "_fetch_market_fund_flow", lambda: _ROWS)
    repository.market_fund_flow_view()
    # 让快照过期，再把数据源打断
    monkeypatch.setattr(repository, "_FUND_FLOW_TTL_SECONDS", -1)

    def _down():
        raise MarketDataError("数据源超时")

    monkeypatch.setattr(repository, "_fetch_market_fund_flow", _down)
    view = repository.market_fund_flow_view()
    assert view["degraded"] is True
    assert len(view["points"]) == 2, "有旧数据就不该报错"
    # **降级必须说出来**：一屏"截至昨天"的图有用，让人以为是今天的就有害
    assert "取不到" in view["note"] and "数据源超时" in view["note"]


def test_一次都没拉到过才让它报错(monkeypatch: pytest.MonkeyPatch) -> None:
    """库里空、数据源也挂——这时候只能如实报错，不能编一屏空图出来。"""
    from stock_decision.database import connection

    with connection() as conn:
        conn.execute("DELETE FROM market_fund_flow")

    def _down():
        raise MarketDataError("数据源超时")

    monkeypatch.setattr(repository, "_fetch_market_fund_flow", _down)
    with pytest.raises(MarketDataError):
        repository.market_fund_flow_view()


def test_同一天重复拉不会堆行(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "_fetch_market_fund_flow", lambda: _ROWS)
    monkeypatch.setattr(repository, "_FUND_FLOW_TTL_SECONDS", -1)
    repository.market_fund_flow_view()
    repository.market_fund_flow_view()
    from stock_decision.database import connection

    with connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM market_fund_flow").fetchone()["n"]
    assert n == 2
