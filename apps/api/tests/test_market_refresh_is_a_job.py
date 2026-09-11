"""同步行情必须是后台任务，不能占着一个 HTTP 请求。

2026-08-19 巡检查出来：这个按钮从上线起就没成功过。
接口返回 200，但一次要跑 25 秒到几分钟（底座是全市场 5544 只，
外部源快慢差很多），而前端默认超时 20 秒 —— 每次都被掐掉，且掐完什么都不显示。

**我第一次的修法是错的**：把前端超时放宽到 90 秒。线上复验时它又超了。
继续加大只是把"静默失败"换成"干等四分钟"。一个要跑几分钟的活
本来就不该同步等 —— 这台机器上「抓取新资讯」早就是后台任务。

这条盯着别改回去。
"""
from __future__ import annotations

import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "stock_decision" / "main.py"


def _handler(path: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(MAIN.read_text())
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and dec.args
                    and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == path):
                return node
    raise AssertionError(f"main.py 里没有 {path} 这个路由")


def test_同步行情返回的是一个后台任务() -> None:
    node = _handler("/api/v1/market/refresh")
    returns = ast.unparse(node.returns) if node.returns else ""
    assert "BackgroundJob" in returns, (
        f"它又变回同步等了（返回 {returns or '没写返回类型'}）——"
        "这活要跑几分钟，同步等的话前端只能靠放宽超时，而那条路 2026-08-19 走过，走不通。"
    )
    body = ast.unparse(node)
    assert "submit(" in body, "没有丢给后台任务队列"


def test_底座失败不拖垮已经刷好的公司行情() -> None:
    """你的公司行情已经刷好了，为了底座把整件事标成失败，等于把拿到的也丢掉。"""
    body = ast.unparse(_handler("/api/v1/market/refresh"))
    assert "refresh_all_market_quotes" in body and "refresh_market_universe" in body, (
        "两样要一起刷 —— 只刷公司的话，首页云图纹丝不动，比两个都旧更迷惑人"
    )
    assert "except Exception" in body, "底座失败没有兜住"


def test_任务说得出底座到底刷没刷成() -> None:
    """「已更新 4 家」和「已更新 4 家、但云图还是旧的」是两件事，得分得出来。"""
    body = ast.unparse(_handler("/api/v1/market/refresh"))
    assert "云图仍是上一次的数" in body, "底座失败时没有在任务结果里说清楚"
