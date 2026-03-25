class TradingAPIError(Exception):
    def __init__(self, message: str, *, code: str = "trading_api_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class TradingValidationError(TradingAPIError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="validation_error")


class TradingConnectionError(TradingAPIError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="connection_error")
