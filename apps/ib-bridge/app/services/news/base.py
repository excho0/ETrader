from __future__ import annotations

from typing import Protocol

from app.models.trading import (
    HistoricalNewsRequest,
    HistoricalNewsResponse,
    NewsArticleResponse,
    NewsProvidersResponse,
)


class NewsServiceAdapter(Protocol):
    source: str

    async def list_providers(self, client) -> NewsProvidersResponse: ...

    async def get_historical_news(
        self,
        client,
        request: HistoricalNewsRequest,
    ) -> HistoricalNewsResponse: ...

    async def get_article(
        self,
        client,
        *,
        provider_code: str,
        article_id: str,
    ) -> NewsArticleResponse: ...
