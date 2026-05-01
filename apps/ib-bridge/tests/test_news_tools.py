from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.trading import HistoricalNewsRequest
from app.services.trading import TradingService


@pytest.mark.asyncio
async def test_get_news_providers_returns_typed_response() -> None:
    service = TradingService(Settings(env="test"))
    service._read_cache.clear()
    service._client = SimpleNamespace(
        news_providers=lambda: None,
    )

    async def news_providers():
        return [
            SimpleNamespace(code="BZ", name="Benzinga Pro"),
            SimpleNamespace(providerCode="DJNL", providerName="Dow Jones Newsletters"),
        ]

    service._client.news_providers = news_providers

    response = await service.get_news_providers()

    assert response.source == "ib"
    assert [(item.code, item.name) for item in response.providers] == [
        ("BZ", "Benzinga Pro"),
        ("DJNL", "Dow Jones Newsletters"),
    ]


@pytest.mark.asyncio
async def test_get_historical_news_uses_available_provider_codes_when_omitted() -> None:
    service = TradingService(Settings(env="test"))
    service._read_cache.clear()

    async def qualify_contract(_request):
        return SimpleNamespace(conId=12345)

    async def news_providers():
        return [SimpleNamespace(code="BZ", name="Benzinga Pro")]

    async def historical_news(**kwargs):
        assert kwargs["con_id"] == 12345
        assert kwargs["provider_codes"] == ["BZ"]
        return [
            SimpleNamespace(
                time="20260501 14:30:00 US/Eastern",
                providerCode="BZ",
                articleId="BZ$abc",
                headline="Sample headline",
            )
        ]

    service._client = SimpleNamespace(
        qualify_contract=qualify_contract,
        news_providers=news_providers,
        historical_news=historical_news,
    )

    response = await service.get_historical_news(HistoricalNewsRequest(symbol="AAPL"))

    assert response.symbol == "AAPL"
    assert response.provider_codes == ["BZ"]
    assert response.headline_count == 1
    assert response.headlines[0].headline == "Sample headline"


@pytest.mark.asyncio
async def test_get_news_article_returns_article_payload() -> None:
    service = TradingService(Settings(env="test"))
    service._read_cache.clear()

    async def news_article(*, provider_code: str, article_id: str):
        assert provider_code == "BZ"
        assert article_id == "BZ$abc"
        return SimpleNamespace(articleType=0, articleText="Body text")

    service._client = SimpleNamespace(news_article=news_article)

    response = await service.get_news_article(provider_code="BZ", article_id="BZ$abc")

    assert response.provider_code == "BZ"
    assert response.article_id == "BZ$abc"
    assert response.article_type == 0
    assert response.article_text == "Body text"
