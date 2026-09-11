"""日线必须有第二条路，而且两个源都要出现在错误里。

## 线上实测（2026-08-18）

`price_history` 作业每次跑十分钟、12 家公司全部失败、0 条数据。
追下去不是网络断了，是**按域名（SNI）的针对性阻断**：

    push2.eastmoney.com     实时行情    正常（茅台 1297.99 秒回）
    push2his.eastmoney.com  历史 K 线   TLS 握手中被重置

决定性证据：同一个 IP、同一个端口，用 `push2.eastmoney.com` 的 SNI 去连返回
404（连上了），用 `push2his` 的 SNI 就被断开。跟 IP、路由、IPv6 都没有关系
—— 这三样我在排查时各判断错过一次，最后是靠换 SNI 那一次试出来的。

而日线**只有一个源**（StockSDK 的 Node 桥，内部走的正是 push2his），
SDK 自己还会重试八次、换四个分片域名 —— 十分钟就是这么耗掉的。

同一台服务器上实测的备选：

    新浪 stock_zh_a_daily      0.5 秒   5984 行   ✅  ← 比原来的主源还快
    腾讯 stock_zh_a_hist_tx   10.0 秒   5984 行   ✅
    东财 stock_zh_a_hist         失败（同样是 push2his）

## 为什么错误里必须两个源都出现

只报一个的话，排查的人会以为只有一条路。而这次的真相恰恰是
**主源被拦、备用源好好的** —— 报错里少那半句，下一个人还要再花一遍力气。
"""

from __future__ import annotations

import ast
import pathlib

API = pathlib.Path(__file__).resolve().parents[1] / "stock_decision"


def test_daily_history_falls_back_to_a_second_source():
    tree = ast.parse((API / "market_data.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_cn_daily_history")
    body = ast.unparse(fn)
    assert "SinaDailyHistoryProvider" in body, (
        "日线又变回只有一个源了 —— 主源（push2his）在服务器上是被拦的，"
        "没有第二条路时整个作业空转十分钟、0 条数据")
    # 必须真的调它，不能只是 import 摆着
    assert "fetch_daily_history" in body


def test_both_sources_are_named_when_both_fail():
    tree = ast.parse((API / "market_data.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_cn_daily_history")
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert raises, "两个都失败时没有抛出任何东西"
    text = " ".join(ast.unparse(r) for r in raises)
    assert "primary" in text and "fallback" in text, (
        "错误里没有同时带上两个源。只报一个的话，排查的人会以为只有一条路 ——"
        "而这次的真相是主源被拦、备用源好好的。")


def test_the_fallback_maps_symbols_to_sina_prefixes():
    """新浪要带市场前缀，映射错了会静静地取不到（或者取到别的股票）。"""
    from stock_decision.providers.sina_daily import _sina_symbol

    assert _sina_symbol("600519") == "sh600519"     # 沪市
    assert _sina_symbol("000333") == "sz000333"     # 深市
    assert _sina_symbol("300750") == "sz300750"     # 创业板归深
    assert _sina_symbol("830799") == "bj830799"     # 北交所
    assert _sina_symbol("sh600519") == "sh600519"   # 已经带前缀的不许再包一层
