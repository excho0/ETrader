from __future__ import annotations

from app.core.instrument_types import InstrumentType, SUPPORTED_INSTRUMENT_TYPES, ensure_supported_instrument_type
from app.services.products.base import ProductAdapter
from app.services.products.stocks import StockProductAdapter

_ADAPTERS: dict[str, ProductAdapter] = {
    "stock": StockProductAdapter(),
}


def get_product_adapter(instrument_type: str | InstrumentType) -> ProductAdapter:
    try:
        return _ADAPTERS[ensure_supported_instrument_type(instrument_type)]
    except KeyError as exc:
        raise ValueError(f"Unsupported instrument_type={instrument_type}") from exc


def list_supported_instrument_types() -> list[InstrumentType]:
    return [InstrumentType(item) for item in SUPPORTED_INSTRUMENT_TYPES]
