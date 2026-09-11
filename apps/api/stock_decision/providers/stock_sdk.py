import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import InvalidSymbolError, QuoteNotFoundError, QuoteProviderError


_CN_SYMBOL = re.compile(r"^(?:(?:SH|SZ|BJ)?(\d{6})|(\d{6})\.(?:SH|SZ|BJ))$", re.IGNORECASE)


def normalize_cn_symbol(symbol: str) -> str:
    """Accept common A-share code forms and return the six-digit database code."""

    match = _CN_SYMBOL.fullmatch(symbol.strip().upper())
    if not match:
        raise InvalidSymbolError("请输入 6 位 A 股代码，例如 600519 或 300750")
    return match.group(1) or match.group(2)


class StockSDKQuoteProvider:
    """Current-quote provider backed by the project's Node StockSDK bridge."""

    provider_id = "stocksdk_quote"
    display_name = "StockSDK"
    category = "行情"
    history_provider_id = "stocksdk_daily_history"
    history_category = "日线行情"
    fund_flow_provider_id = "stocksdk_market_fund_flow"
    fund_flow_category = "大盘资金流"

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[4]
        self.bridge_script = self.project_root / "scripts" / "stock-sdk-quotes.mjs"
        self._fund_flow_cache: list[dict[str, Any]] = []
        self._fund_flow_cached_at = 0.0

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        canonical_symbols = [normalize_cn_symbol(symbol) for symbol in symbols]
        if not canonical_symbols:
            return []
        try:
            completed = subprocess.run(
                ["node", str(self.bridge_script)],
                cwd=self.project_root,
                input=json.dumps({"symbols": canonical_symbols}),
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QuoteProviderError("StockSDK 启动或请求超时") from exc
        if completed.returncode != 0:
            raise QuoteProviderError(completed.stderr.strip() or "StockSDK 请求失败")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise QuoteProviderError("StockSDK 返回的数据无法解析") from exc
        if not isinstance(payload, list):
            raise QuoteProviderError("StockSDK 未返回行情列表")
        return [quote for quote in payload if isinstance(quote, dict) and quote.get("code")]

    def resolve_quote(self, symbol: str) -> dict[str, Any]:
        canonical_symbol = normalize_cn_symbol(symbol)
        quotes = self.fetch_quotes([canonical_symbol])
        for quote in quotes:
            if str(quote.get("code")) == canonical_symbol and str(quote.get("name") or "").strip():
                return quote
        raise QuoteNotFoundError(f"未找到 A 股代码 {canonical_symbol} 的有效行情")

    def fetch_daily_history(self, symbol: str) -> list[dict[str, Any]]:
        canonical_symbol = normalize_cn_symbol(symbol)
        try:
            completed = subprocess.run(
                ["node", str(self.bridge_script)],
                cwd=self.project_root,
                input=json.dumps({"action": "daily_history", "symbol": canonical_symbol}),
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QuoteProviderError("StockSDK 日线数据请求超时") from exc
        if completed.returncode != 0:
            raise QuoteProviderError(completed.stderr.strip() or "StockSDK 日线数据请求失败")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise QuoteProviderError("StockSDK 日线数据无法解析") from exc
        if not isinstance(payload, list):
            raise QuoteProviderError("StockSDK 未返回日线数据列表")
        return [bar for bar in payload if isinstance(bar, dict) and isinstance(bar.get("date"), str) and isinstance(bar.get("close"), (int, float))]

    def fetch_market_fund_flow(self) -> list[dict[str, Any]]:
        """Fetch StockSDK's real whole-market order-size flow history.

        The dashboard can be opened repeatedly, so keep a short process-local cache.
        If the upstream has a brief outage after a successful read, the last real
        snapshot is safer than replacing the chart with invented numbers.
        """

        if self._fund_flow_cache and time.monotonic() - self._fund_flow_cached_at < 300:
            return self._fund_flow_cache
        try:
            completed = subprocess.run(
                ["node", str(self.bridge_script)],
                cwd=self.project_root,
                input=json.dumps({"action": "market_fund_flow"}),
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if self._fund_flow_cache:
                return self._fund_flow_cache
            raise QuoteProviderError("StockSDK 大盘资金流请求超时") from exc
        if completed.returncode != 0:
            if self._fund_flow_cache:
                return self._fund_flow_cache
            raise QuoteProviderError(completed.stderr.strip() or "StockSDK 大盘资金流请求失败")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            if self._fund_flow_cache:
                return self._fund_flow_cache
            raise QuoteProviderError("StockSDK 大盘资金流数据无法解析") from exc
        if not isinstance(payload, list):
            raise QuoteProviderError("StockSDK 未返回大盘资金流列表")
        rows = [row for row in payload if isinstance(row, dict) and isinstance(row.get("date"), str)]
        if not rows:
            raise QuoteProviderError("StockSDK 暂无大盘资金流数据")
        self._fund_flow_cache = rows
        self._fund_flow_cached_at = time.monotonic()
        return rows
