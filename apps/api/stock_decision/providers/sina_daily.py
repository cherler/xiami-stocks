"""日线的备用源：新浪。

## 为什么需要它

2026-08-18 线上排查：`price_history` 作业每次跑十分钟、12 家公司全部失败、
0 条数据。追下去不是网络断了，是**按域名（SNI）的针对性阻断** ——

    push2.eastmoney.com     实时行情    正常（茅台 1297.99 秒回）
    push2his.eastmoney.com  历史 K 线   TLS 握手中被重置

决定性证据：同一个 IP、同一个端口，用 `push2.eastmoney.com` 的 SNI 去连返回
404（通了），用 `push2his` 的 SNI 就被断。跟 IP、路由、IPv6 都没有关系
（这三个我都试过并且都判断错过一次）。

而日线原来**只有一个源**：StockSDK 的 Node 桥，而它内部走的正是 push2his，
SDK 自己重试八次、换四个分片域名，全部失败 —— 十分钟就是这么耗掉的。

## 为什么选新浪

在同一台服务器上实测：

    新浪 stock_zh_a_daily      0.5 秒   5984 行   ✅
    腾讯 stock_zh_a_hist_tx   10.0 秒   5984 行   ✅
    东财 stock_zh_a_hist         失败（同样是 push2his）

新浪比原来的主源还快。腾讯留作第三条路 —— 它慢二十倍，只在新浪也不行时用。
"""

from __future__ import annotations

from typing import Any

from .base import QuoteProviderError


def _sina_symbol(symbol: str) -> str:
    """600519 → sh600519。新浪要带市场前缀。"""
    code = str(symbol or "").strip()[-6:]
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _rows(frame: Any, date_key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        raw_date = row.get(date_key)
        if raw_date is None:
            continue
        text = str(raw_date)[:10]
        try:
            close = float(row.get("close") if "close" in row else row.get("收盘"))
        except (TypeError, ValueError):
            continue
        def num(*keys: str) -> float | None:
            for key in keys:
                if key in row and row[key] is not None:
                    try:
                        return float(row[key])
                    except (TypeError, ValueError):
                        return None
            return None
        out.append({"date": text, "close": close,
                    "open": num("open", "开盘"), "high": num("high", "最高"),
                    "low": num("low", "最低"), "volume": num("volume", "成交量")})
    return out


class SinaDailyHistoryProvider:
    """前复权日线。**只做一件事**：主源挂了的时候还能拿到日线。"""

    provider_id = "sina_daily_history"
    display_name = "新浪财经·前复权日线"
    category = "行情"

    def fetch_daily_history(self, symbol: str) -> list[dict[str, Any]]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，取不到备用日线") from exc
        try:
            frame = ak.stock_zh_a_daily(symbol=_sina_symbol(symbol), adjust="qfq")
        except Exception as exc:  # noqa: BLE001 —— 网络什么都可能抛
            raise QuoteProviderError(f"新浪日线取不到：{type(exc).__name__}") from exc
        bars = _rows(frame, "date")
        if not bars:
            raise QuoteProviderError("新浪日线返回了空表")
        return bars
