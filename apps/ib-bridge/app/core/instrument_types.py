from enum import StrEnum


class InstrumentType(StrEnum):
    STOCK = "stock"
    FOREX = "forex"


SUPPORTED_INSTRUMENT_TYPES: tuple[str, ...] = tuple(item.value for item in InstrumentType)


def ensure_supported_instrument_type(instrument_type: str | InstrumentType) -> InstrumentType:
    normalized = str(instrument_type).strip().lower()
    if normalized not in SUPPORTED_INSTRUMENT_TYPES:
        supported = ", ".join(SUPPORTED_INSTRUMENT_TYPES)
        raise ValueError(
            f"Unsupported instrument_type={instrument_type!r}. Supported instrument types: {supported}"
        )
    return InstrumentType(normalized)
