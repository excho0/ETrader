import logging
from logging.config import dictConfig
from pathlib import Path


class SuppressHealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_line = getattr(record, "request_line", "")
        if isinstance(request_line, str) and (
            "/api/v1/health" in request_line or "/mcp" in request_line
        ):
            return False
        return True


def configure_logging(
    level: str,
    *,
    log_path: str | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    normalized_level = getattr(logging, level.upper(), logging.INFO)
    handlers: dict[str, dict[str, object]] = {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "uvicorn_access",
            "filters": ["suppress_health_access"],
        },
    }

    root_handlers = ["default"]
    uvicorn_access_handlers = ["access"]

    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "plain",
            "filename": log_path,
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
        }
        handlers["access_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "access_plain",
            "filename": log_path,
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
        }
        root_handlers.append("file")
        uvicorn_access_handlers.append("access_file")

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
                "plain": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                },
                "uvicorn_access": {
                    "()": "uvicorn.logging.AccessFormatter",
                    "fmt": "%(levelprefix)s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
                    "use_colors": True,
                },
                "access_plain": {
                    "format": "%(asctime)s | %(levelname)s | %(client_addr)s | %(request_line)s | %(status_code)s",
                },
            },
            "handlers": handlers,
            "filters": {
                "suppress_health_access": {
                    "()": SuppressHealthAccessFilter,
                },
            },
            "root": {
                "level": normalized_level,
                "handlers": root_handlers,
            },
            "loggers": {
                "uvicorn": {
                    "level": "INFO",
                    "handlers": root_handlers,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "level": "INFO",
                    "handlers": root_handlers,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "level": "INFO",
                    "handlers": uvicorn_access_handlers,
                    "propagate": False,
                },
                "ib_async": {
                    "level": "INFO",
                    "handlers": root_handlers,
                    "propagate": False,
                },
                "uvicorn.app": {
                    "level": normalized_level,
                    "handlers": root_handlers,
                    "propagate": False,
                },
            },
        }
    )
