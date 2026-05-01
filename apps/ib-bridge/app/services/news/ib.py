from __future__ import annotations

from datetime import UTC, datetime

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
        return NewsProvidersResponse(
            source=self.source,
            providers=[
                NewsProviderResponse(
                    code=str(getattr(provider, "code", "") or getattr(provider, "providerCode", "")),
                    name=str(getattr(provider, "name", "") or getattr(provider, "providerName", "")),
                )
                for provider in providers
            ],
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
                provider_code=str(getattr(item, "providerCode", "")),
                article_id=str(getattr(item, "articleId", "")),
                headline=str(getattr(item, "headline", "")),
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
        return NewsArticleResponse(
            provider_code=provider_code,
            article_id=article_id,
            article_type=int(getattr(article, "articleType", 0)),
            article_text=str(getattr(article, "articleText", "")),
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
