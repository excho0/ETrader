from __future__ import annotations

from app.services.news.base import NewsServiceAdapter
from app.services.news.ib import IBNewsServiceAdapter

_ADAPTERS: dict[str, NewsServiceAdapter] = {
    "ib": IBNewsServiceAdapter(),
}


def get_news_adapter(source: str = "ib") -> NewsServiceAdapter:
    try:
        return _ADAPTERS[source]
    except KeyError as exc:
        raise ValueError(f"Unsupported news source={source}") from exc
