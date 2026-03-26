from __future__ import annotations

from app.services.products.base import ProductAdapter
from app.services.products.stocks import StockProductAdapter

_ADAPTERS: dict[str, ProductAdapter] = {
    "stock": StockProductAdapter(),
}


def get_product_adapter(instrument_type: str) -> ProductAdapter:
    try:
        return _ADAPTERS[instrument_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported instrument_type={instrument_type}") from exc
