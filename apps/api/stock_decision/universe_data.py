"""Boundary for the whole-market base layer (全 A + 主要指数)."""

from typing import Any

from .providers import AkShareSentimentProvider, AkShareTrendProvider, AkShareUniverseProvider, QuoteProviderError


class UniverseDataError(QuoteProviderError):
    pass


universe_provider = AkShareUniverseProvider()
sentiment_provider = AkShareSentimentProvider()
trend_provider = AkShareTrendProvider()


def fetch_market_spot() -> dict[str, Any]:
    try:
        return universe_provider.fetch_spot()
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_market_fundamentals(report_date: str) -> dict[str, Any]:
    try:
        return universe_provider.fetch_fundamentals(report_date)
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_index_members() -> dict[str, Any]:
    try:
        return universe_provider.fetch_index_members()
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_market_dividends(period: str) -> dict[str, Any]:
    """全市场股息率与派息。走东财 datacenter，与被墙的 push2 行情不是一条路。"""
    try:
        return universe_provider.fetch_dividends(period)
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_market_sentiment() -> dict[str, Any]:
    """全市场情绪面：人气排名、关注指数、机构参与度。

    **这些数要反着读**：高人气意味着已经被充分讨论，对长期研究者是减分不是加分。
    """
    try:
        return sentiment_provider.fetch_sentiment()
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_market_trend() -> dict[str, Any]:
    """全市场趋势面：量价齐升、突破均线、创新高、持续放量。

    **走同花顺不走东财**：底座的行情快照已经降级到新浪，60 日涨跌与换手率
    在库里覆盖率是 0，而东财那两条能给区间涨跌的路都被挡着。
    """
    try:
        return trend_provider.fetch_trend()
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc


def fetch_sw_industries() -> dict[str, Any]:
    """申万一级/二级行业分类与各自的估值、股息率。"""
    try:
        return universe_provider.fetch_sw_industries()
    except QuoteProviderError as exc:
        raise UniverseDataError(str(exc)) from exc
