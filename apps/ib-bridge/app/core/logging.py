import logging
from logging.config import dictConfig


class SuppressHealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_line = getattr(record, "request_line", "")
        if isinstance(request_line, str) and (
            "/api/v1/health" in request_line or "/mcp" in request_line
        ):
            return False
        return True


def configure_logging(level: str) -> None:
    normalized_level = getattr(logging, level.upper(), logging.INFO)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "fmt": "%(levelprefix)s | %(name)s | %(message)s",
                    "use_colors": True,
                },
                "uvicorn_access": {
                    "()": "uvicorn.logging.AccessFormatter",
                    "fmt": "%(levelprefix)s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
                    "use_colors": True,
                },
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                },
                "access": {
                    "class": "logging.StreamHandler",
                    "formatter": "uvicorn_access",
                    "filters": ["suppress_health_access"],
                },
            },
            "filters": {
                "suppress_health_access": {
                    "()": SuppressHealthAccessFilter,
                },
            },
            "root": {
                "level": normalized_level,
                "handlers": ["default"],
            },
            "loggers": {
                "uvicorn": {
                    "level": "INFO",
                    "handlers": ["default"],
                    "propagate": False,
                },
                "uvicorn.error": {
                    "level": "INFO",
                    "handlers": ["default"],
                    "propagate": False,
                },
                "uvicorn.access": {
                    "level": "INFO",
                    "handlers": ["access"],
                    "propagate": False,
                },
                "ib_async": {
                    "level": "INFO",
                    "handlers": ["default"],
                    "propagate": False,
                },
                "uvicorn.app": {
                    "level": normalized_level,
                    "handlers": ["default"],
                    "propagate": False,
                },
            },
        }
    )
