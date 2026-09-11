"""Boundary for report-period financial data providers."""

from typing import Any

from .providers import AkShareFinancialProvider, QuoteProviderError


class FinancialDataError(QuoteProviderError):
    pass


financial_provider = AkShareFinancialProvider()


def fetch_financial_periods(symbol: str) -> list[dict[str, Any]]:
    try:
        return financial_provider.fetch_financial_periods(symbol)
    except QuoteProviderError as exc:
        raise FinancialDataError(str(exc)) from exc
