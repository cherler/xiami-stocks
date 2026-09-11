"""Boundary for historical valuation providers (PE TTM / PB 序列)."""

from typing import Any

from .providers import AkShareValuationProvider, QuoteProviderError


class ValuationDataError(QuoteProviderError):
    pass


valuation_provider = AkShareValuationProvider()


def fetch_valuation_history(symbol: str) -> dict[str, Any]:
    try:
        return valuation_provider.fetch_valuation_history(symbol)
    except QuoteProviderError as exc:
        raise ValuationDataError(str(exc)) from exc
