from typing import Any, Protocol


class QuoteProviderError(RuntimeError):
    """A market-data provider could not serve a request."""


class InvalidSymbolError(QuoteProviderError):
    """The user supplied a symbol outside the provider's supported format."""


class QuoteNotFoundError(QuoteProviderError):
    """The provider responded successfully but did not know the symbol."""


class QuoteProvider(Protocol):
    """Contract for a replaceable source of current market quotes."""

    provider_id: str
    display_name: str
    category: str

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]: ...


class PriceHistoryProvider(Protocol):
    """Contract for adjusted daily closing prices used in long-term review."""

    history_provider_id: str
    display_name: str
    history_category: str

    def fetch_daily_history(self, symbol: str) -> list[dict[str, Any]]: ...


class FinancialProvider(Protocol):
    """Contract for report-period financial facts from a traceable source."""

    provider_id: str
    display_name: str
    category: str

    def fetch_financial_periods(self, symbol: str) -> list[dict[str, Any]]: ...
