from __future__ import annotations

from datetime import UTC, datetime

from bs4 import BeautifulSoup

from app.models.trading import (
    HistoricalNewsHeadlineResponse,
    HistoricalNewsRequest,
    HistoricalNewsResponse,
    NewsArticleResponse,
    NewsProviderResponse,
    NewsProvidersResponse,
)
from app.services.news.base import NewsServiceAdapter


class IBNewsServiceAdapter(NewsServiceAdapter):
    source = "ib"

    async def list_providers(self, client) -> NewsProvidersResponse:
        providers = await client.news_providers()
        normalized_providers: list[NewsProviderResponse] = []
        seen_codes: set[str] = set()
        for provider in providers:
            code = str(getattr(provider, "code", "") or getattr(provider, "providerCode", "")).strip().upper()
            name = str(getattr(provider, "name", "") or getattr(provider, "providerName", "")).strip()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            normalized_providers.append(NewsProviderResponse(code=code, name=name or code))
        return NewsProvidersResponse(
            source=self.source,
            providers=normalized_providers,
        )

    async def get_historical_news(
        self,
        client,
        request: HistoricalNewsRequest,
    ) -> HistoricalNewsResponse:
        contract = await client.qualify_contract(request)
        provider_codes = request.provider_codes or [
            provider.code for provider in (await self.list_providers(client)).providers if provider.code
        ]
        if not provider_codes:
            raise ValueError("No news providers are available for the connected IB session")
        headlines = await client.historical_news(
            con_id=int(contract.conId),
            provider_codes=provider_codes,
            start_date_time=request.start_date_time,
            end_date_time=request.end_date_time,
            total_results=request.total_results,
        )
        normalized = [
            HistoricalNewsHeadlineResponse(
                time=self._normalize_time(getattr(item, "time", None)),
                provider_code=str(getattr(item, "providerCode", "")).strip().upper(),
                article_id=str(getattr(item, "articleId", "")),
                headline=self._normalize_text(str(getattr(item, "headline", ""))),
            )
            for item in headlines
        ]
        return HistoricalNewsResponse(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
            provider_codes=provider_codes,
            start_date_time=request.start_date_time,
            end_date_time=request.end_date_time,
            total_results=request.total_results,
            headline_count=len(normalized),
            headlines=normalized,
            source=self.source,
        )

    async def get_article(
        self,
        client,
        *,
        provider_code: str,
        article_id: str,
    ) -> NewsArticleResponse:
        article = await client.news_article(provider_code=provider_code, article_id=article_id)
        article_text = str(getattr(article, "articleText", ""))
        return NewsArticleResponse(
            provider_code=provider_code.strip().upper(),
            article_id=article_id,
            article_type=int(getattr(article, "articleType", 0)),
            article_text=article_text,
            article_text_plain=self._html_to_text(article_text),
            source=self.source,
        )

    @staticmethod
    def _normalize_time(raw: object) -> str:
        if isinstance(raw, datetime):
            dt = raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
            return dt.astimezone(UTC).isoformat()
        if raw is None:
            return ""
        return str(raw)

    @classmethod
    def _html_to_text(cls, raw: str) -> str:
        if not raw:
            return ""
        soup = BeautifulSoup(raw, "html.parser")
        return cls._normalize_text(soup.get_text(separator="\n"))

    @staticmethod
    def _normalize_text(raw: str) -> str:
        lines = [line.strip() for line in raw.replace("\r", "\n").split("\n")]
        compact = "\n".join(line for line in lines if line)
        return compact.strip()
