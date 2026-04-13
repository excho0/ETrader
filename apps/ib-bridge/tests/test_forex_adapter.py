from types import SimpleNamespace

from app.core.instrument_types import InstrumentType, ensure_supported_instrument_type
from app.models.trading import InstrumentContractSpec
from app.services.products.forex import ForexProductAdapter
from app.services.products.registry import get_product_adapter, list_supported_instrument_types
from app.services.trading import TradingService


def test_forex_instrument_type_is_supported() -> None:
    assert ensure_supported_instrument_type("forex") is InstrumentType.FOREX
    assert InstrumentType.FOREX in list_supported_instrument_types()


def test_registry_returns_forex_adapter() -> None:
    adapter = get_product_adapter("forex")
    assert isinstance(adapter, ForexProductAdapter)


def test_forex_adapter_normalizes_symbol_and_currency_pair() -> None:
    base, quote = ForexProductAdapter._normalize_pair(
        InstrumentContractSpec(instrument_type="forex", symbol="eur", currency="usd")
    )
    assert (base, quote) == ("EUR", "USD")


def test_forex_adapter_normalizes_compact_pair() -> None:
    base, quote = ForexProductAdapter._normalize_pair(
        InstrumentContractSpec(instrument_type="forex", symbol="eurusd", currency="usd")
    )
    assert (base, quote) == ("EUR", "USD")


def test_forex_specs_default_to_idealpro_when_exchange_is_omitted() -> None:
    spec = InstrumentContractSpec(instrument_type="forex", symbol="eurusd", exchange="SMART", currency="usd")

    assert spec.exchange == "IDEALPRO"
    assert spec.currency == "USD"


def test_forex_adapter_maps_smart_to_idealpro() -> None:
    contract = ForexProductAdapter._build_contract(
        InstrumentContractSpec(instrument_type="forex", symbol="eurusd", exchange="SMART", currency="USD")
    )

    assert contract.exchange == "IDEALPRO"


def test_open_order_response_infers_forex_type() -> None:
    trade = SimpleNamespace(
        contract=SimpleNamespace(symbol="EUR", secType="CASH", exchange="IDEALPRO", currency="USD"),
        order=SimpleNamespace(
            orderId=1,
            permId=2,
            clientId=11,
            action="BUY",
            orderType="LMT",
            totalQuantity=10000,
            lmtPrice=1.1,
            auxPrice=None,
            tif="DAY",
        ),
        orderStatus=SimpleNamespace(status="Submitted"),
    )

    response = TradingService._open_order_response(trade)

    assert response.instrument_type is InstrumentType.FOREX
    assert response.symbol == "EUR"
