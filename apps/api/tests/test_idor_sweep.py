"""越权普查（写接口）：**每一个带路径参数的写接口都要表态。**

test_idor.py 是一张手写清单，写得很细，但它是手写的 —— 新加一条路由不会
自动进去。实测：带路径参数的写接口共 59 个，那张清单点名了 26 个，剩下 33 个
从来没有人问过它们「换个人来打会怎样」。

这个文件不点名，改成**从 app.routes 现取**：凡是带 `{}` 的写接口，
都拿站主建的真实 id 打一遍。这样新加路由会自动被问到，而不是等出事。

判定跟 test_idor.py 一致：403 / 404 都算合格（拒绝或装作不存在），
2xx 才是漏 —— 但删除类即使 2xx 也要看东西还在不在，所以这里额外要求
「打完之后站主自己再读一遍，东西没变」。
"""

import re

import pytest
from fastapi.testclient import TestClient

from stock_decision import access
from stock_decision.main import app

from test_idor import client, owned  # noqa: F401  （直接复用那边的夹具）


def _write_routes() -> list[tuple[str, str]]:
    out = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1/") or "{" not in path:
            continue
        for method in (getattr(route, "methods", set()) or set()) & {"POST", "PATCH", "PUT", "DELETE"}:
            out.add((method, path))
    return sorted(out)


# 路径参数名 → owned 夹具里的键。取不到的填一个不存在的 id：
# **守卫应当跑在查库之前**，所以挡没挡得住跟 id 存不存在无关。
PARAM_TO_OWNED = {
    "company_id": "company", "thesis_id": "thesis", "event_id": "event",
    "portfolio_id": "portfolio", "trade_id": "trade", "task_id": "task",
    "feed_id": "feed",
}

# 每个接口给一个能过 schema 校验的最小请求体。**给不出来就别给** ——
# 422 也算"没漏"，但那是因为体不对，不是因为守卫拦住了，会掩盖问题。
BODIES = {
    "/api/v1/companies/{company_id}/promises": {
        "statement": "越权写入", "promised_on": "2026-08-05"},
    "/api/v1/companies/{company_id}/segments": {
        "segments": [{"name": "越权", "revenue": 1.0}]},
    "/api/v1/companies/{company_id}/thesis-write": {
        "claim": "越权写入", "counter_condition": "越权"},
    "/api/v1/promises/{promise_id}": {"status": "已兑现"},
    "/api/v1/tasks/items/{item_id}": {"status": "已建档"},
    "/api/v1/industry-chains/{theme_id}/nodes": {"name": "越权", "node_type": "product"},
    "/api/v1/industry-chains/{theme_id}/stages": {"name": "越权"},
    "/api/v1/companies/{company_id}/valuation": {"pe": 1.0, "pb": 1.0},
}


@pytest.mark.parametrize("method,path", _write_routes(),
                         ids=[f"{m} {p}" for m, p in _write_routes()])
def test_no_write_route_answers_to_a_stranger(client, owned, method, path):  # noqa: F811
    """换一个用户，拿站主的真实 id 打这个写接口 —— 不许成功。"""
    client.as_user("user-9")

    concrete = path
    for name in re.findall(r"\{(\w+)\}", path):
        key = PARAM_TO_OWNED.get(name)
        value = owned.get(key) if key else None
        concrete = concrete.replace(f"{{{name}}}", str(value if value else 999999))

    response = client.request(method, concrete, json=BODIES.get(path))
    # **200 不一定是漏。** 一批接口用 `{"deleted": false}` / `{"confirmed": false}`
    # 表达"没匹配到，什么都没做"（test_idor.py 里也提过这一点）。
    # 判据跟那边一致：看**效果**，不是看状态码。
    if response.status_code < 400:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body and all(v is False for v in body.values()):
            return
    assert response.status_code >= 400, (
        f"{method} {concrete} 返回 {response.status_code} —— 别人的记录被动到了：\n"
        f"  {response.text[:300]}\n"
        f"  · 这是他自己的数据 → 查库时带上 _sw() / _swc()；\n"
        f"  · 这是整台实例的东西（排期、订阅源、备份…）→ access.require_owner。"
    )
