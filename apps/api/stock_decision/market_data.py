"""Compatibility facade for the active quote provider.

New providers live in ``stock_decision.providers``.  Keeping this small module
allows the rest of the application to depend on a stable market-data boundary.
"""

from datetime import datetime
from typing import Any

from .providers import InvalidSymbolError, QuoteNotFoundError, QuoteProviderError, StockSDKQuoteProvider


class MarketDataError(QuoteProviderError):
    pass


class MarketSymbolError(MarketDataError):
    pass


class MarketQuoteNotFoundError(MarketDataError):
    pass


STARTER_SYMBOLS = ["600519", "000333", "300750"]
quote_provider = StockSDKQuoteProvider()


def fetch_cn_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    try:
        return quote_provider.fetch_quotes(symbols)
    except QuoteProviderError as exc:
        raise MarketDataError(str(exc)) from exc


def resolve_cn_quote(symbol: str) -> dict[str, Any]:
    try:
        return quote_provider.resolve_quote(symbol)
    except InvalidSymbolError as exc:
        raise MarketSymbolError(str(exc)) from exc
    except QuoteNotFoundError as exc:
        raise MarketQuoteNotFoundError(str(exc)) from exc
    except QuoteProviderError as exc:
        raise MarketDataError(str(exc)) from exc


def fetch_cn_daily_history(symbol: str) -> list[dict[str, Any]]:
    """前复权日线。**主源挂了就换新浪，别让整个作业空转十分钟。**

    2026-08-18 线上：主源（StockSDK → push2his.eastmoney.com）被按域名阻断，
    price_history 作业每次跑十分钟、12 家全失败、0 条数据 —— 而 SDK 自己
    还会重试八次换四个分片域名，时间就是这么耗掉的。

    日线原来只有这一个源。新浪在同一台机器上 0.5 秒返回 5984 行，
    比原来的主源还快。
    """
    from .providers.sina_daily import SinaDailyHistoryProvider

    try:
        return quote_provider.fetch_daily_history(symbol)
    except QuoteProviderError as primary:
        try:
            return SinaDailyHistoryProvider().fetch_daily_history(symbol)
        except QuoteProviderError as fallback:
            # **两个源都要在错误里出现。** 只报一个的话，排查时会以为
            # 只有一条路 —— 而这次的真相恰恰是"主源被拦、备用源好好的"。
            raise MarketDataError(
                f"日线两个来源都取不到：主源 {primary}；新浪 {fallback}") from fallback


def fetch_market_fund_flow() -> list[dict[str, Any]]:
    try:
        return quote_provider.fetch_market_fund_flow()
    except QuoteProviderError as exc:
        raise MarketDataError(str(exc)) from exc


def quote_timestamp(quote: dict[str, Any]) -> str | None:
    timestamp = quote.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp / 1000).astimezone().replace(microsecond=0).isoformat()
    return None
