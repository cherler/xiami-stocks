"""积分闸口宕掉时：先记账，连着漏太多就停手。

## 这条测的是一个**故意保留**的行为的边界

`llm.reserve()` 里写着：闸口连不上 ≠ 用户没钱，所以主站抖一下的时候
不挡住调用。这个判断是对的，不改。改的是它**没有上限**这件事——
闸口宕一天就免费送一天，而且账上一点痕迹都没有。

所以这里要证明三件事：

1. 闸口不可达时调用照样能跑（原来的行为不能丢）；
2. 但每一次都落进未计费台账，跑完还要把实际用量补上——否则「漏了多少」算不出来；
3. 连着漏超过阈值就抛 CreditsError，不再继续免费送。
"""

import time

import pytest

from stock_decision import billing_ledger, llm


@pytest.fixture(autouse=True)
def _clean_ledger():
    from stock_decision.database import connection

    with connection() as conn:
        conn.execute("DELETE FROM unbilled_calls")
    yield


def _gate_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """把闸口打成"连不上"，并让 reserve 认为已经接入、身份也有。"""
    monkeypatch.setattr(llm, "load_env", lambda: {
        "XM_API_BASE": "http://127.0.0.1:9/不存在", "XM_CREDIT_MODULE": "stocks"})
    monkeypatch.setattr(llm, "_post", lambda *a, **k: (_ for _ in ()).throw(OSError("连不上")))
    monkeypatch.setattr(llm, "background_principal",
                        lambda: llm.Principal(cookie="c", user_id="u1", internal_key=""))


def test_闸口连不上时调用照跑_但要落台账(monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_down(monkeypatch)
    meter = llm.reserve("stocks", "deep-report", estimated_tokens=8000, searches=2)
    assert meter.active is False, "闸口连不上不该假装计上了费"
    assert "未计费" in meter.note
    rows = billing_ledger.pending()
    assert len(rows) == 1
    assert rows[0]["reason"] == billing_ledger.REASON_UNREACHABLE
    assert rows[0]["estimated_tokens"] == 8000


def test_跑完之后要把实际用量补进台账(monkeypatch: pytest.MonkeyPatch) -> None:
    """**只记「漏了一次」是不够的**，对账要的是漏了多少钱。"""
    _gate_down(monkeypatch)
    meter = llm.reserve("stocks", "deep-report", estimated_tokens=8000, searches=2)
    meter.commit(12000)   # 实际烧掉的 token
    row = billing_ledger.pending()[0]
    assert row["tokens"] == 12000
    assert row["credits_estimate"] == llm.credits_for_report(2, 12000)
    assert row["credits_estimate"] > 0


def test_连着漏超过阈值就停手(monkeypatch: pytest.MonkeyPatch) -> None:
    _gate_down(monkeypatch)
    for _ in range(billing_ledger.MAX_UNBILLED_IN_WINDOW):
        llm.reserve("stocks", "chat", estimated_tokens=100)     # 这些都放行
    with pytest.raises(llm.CreditsError) as caught:
        llm.reserve("stocks", "chat", estimated_tokens=100)     # 这一次开始拒绝
    assert caught.value.code == "gate_down"
    assert "积分服务" in str(caught.value)
    # **压垮骆驼的那一次也要记进账**：先记账再判断，顺序反了它就丢了
    assert len(billing_ledger.pending()) == billing_ledger.MAX_UNBILLED_IN_WINDOW + 1


def test_对完账之后熔断自动松开(monkeypatch: pytest.MonkeyPatch) -> None:
    """`settle()` 只盖时间戳、不删行；而计数只数没对过账的，所以对完账就能继续。"""
    _gate_down(monkeypatch)
    for _ in range(billing_ledger.MAX_UNBILLED_IN_WINDOW + 1):
        try:
            llm.reserve("stocks", "chat", estimated_tokens=100)
        except llm.CreditsError:
            pass
    assert billing_ledger.paused() is True
    settled = billing_ledger.settle("闸口恢复后已人工对账")
    assert settled >= billing_ledger.MAX_UNBILLED_IN_WINDOW
    assert billing_ledger.paused() is False
    assert billing_ledger.pending() == []


def test_本地单机不落账也不熔断(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 XM_API_BASE 时本来就不计费，**不能算成漏计**——
    否则本机开发跑二十次就把自己锁死了。"""
    monkeypatch.setattr(llm, "load_env", lambda: {"XM_API_BASE": "", "XM_CREDIT_MODULE": "stocks"})
    for _ in range(billing_ledger.MAX_UNBILLED_IN_WINDOW + 5):
        meter = llm.reserve("stocks", "chat", estimated_tokens=100)
        assert meter.active is False
    assert billing_ledger.pending() == []
    assert billing_ledger.paused() is False


def test_时间窗之外的不算数(monkeypatch: pytest.MonkeyPatch) -> None:
    """熔断看的是**最近**十分钟。昨天宕过一次，不该影响今天。"""
    from stock_decision.database import connection

    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3 * 3600))
    with connection() as conn:
        for i in range(billing_ledger.MAX_UNBILLED_IN_WINDOW + 10):
            conn.execute(
                "INSERT INTO unbilled_calls (module, task, reason, created_at) VALUES (?, ?, ?, ?)",
                ("stocks", f"old-{i}", billing_ledger.REASON_UNREACHABLE, old))
    assert billing_ledger.recent_count() == 0
    assert billing_ledger.paused() is False


def test_熔断要以402返回_不能被改写成503(monkeypatch: pytest.MonkeyPatch) -> None:
    """**这条是本地真跑一遍才发现的。**

    单测直接调 `llm.reserve()`，看到的是抛出来的 CreditsError，一切正常。
    而真实请求要经过接口那一层，那里写着：

        except RuntimeError as exc:
            raise HTTPException(503, ...)

    `CreditsError` 是 `RuntimeError` 的子类 —— 于是熔断触发时用户拿到的是
    503「服务暂时不可用」。差别不只是数字：503 的意思是「等会儿再试」，
    前端会照着重试；而 402 才会走到"额度/计费"那套提示上。

    实测记录：本机起一个闸口指向死端口的实例，连打 21 次体检，
    第 21 次返回的是 503 + 熔断文案。修完再打，是 402。
    """
    import asyncio

    from stock_decision import main

    from tests.test_api import _seed_universe, _universe_row, request

    _seed_universe(monkeypatch, [_universe_row("600519", "贵州茅台")])
    company = asyncio.run(request("POST", "/api/v1/companies",
                                  {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"})).json()

    def _tripped(_company_id):
        raise llm.CreditsError("积分服务连不上，为避免漏计费，AI 功能暂时停用；恢复后会自动放开。", "gate_down")

    monkeypatch.setattr(main, "run_assessment", _tripped)
    response = asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/assessment"))
    assert response.status_code == 402, f"熔断被改写成了 {response.status_code}"
    assert response.json()["code"] == "gate_down"
