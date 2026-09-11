"""Boundary for company-profile providers (概况、股本、分红、解禁、公告)."""

from typing import Any

from .providers import AkShareCompanyProfileProvider, QuoteProviderError


class CompanyProfileError(QuoteProviderError):
    pass


company_profile_provider = AkShareCompanyProfileProvider()


def fetch_company_profile(symbol: str) -> dict[str, Any]:
    try:
        return company_profile_provider.fetch_company_profile(symbol)
    except QuoteProviderError as exc:
        raise CompanyProfileError(str(exc)) from exc
