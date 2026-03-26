from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ETrader IB Bridge"
    app_version: str = "0.1.0"
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8040
    auth_enabled: bool = True
    auth_agent_token: str | None = None
    auth_execute_token: str | None = None
    mcp_http_localhost_auth_bypass: bool = True
    mcp_http_localhost_bypass_scope: Literal["agent", "execute"] = "execute"
    mcp_stdio_auth_bypass: bool = True
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8041
    mcp_http_issuer_url: str = "http://127.0.0.1:8041"
    mcp_http_resource_server_url: str = "http://127.0.0.1:8041"

    ib_target_mode: Literal["paper", "live", "auto"] = "paper"
    ib_preferred_mode: Literal["paper", "live"] = "paper"
    ib_host: str = "127.0.0.1"
    ib_port: int | None = None
    ib_paper_port: int = 4002
    ib_live_port: int = 4001
    ib_client_id: int = 11
    ib_read_only: bool = True
    ib_connect_timeout_seconds: float = 10.0
    ib_request_timeout_seconds: float = 30.0
    ib_auto_reconnect: bool = True
    ib_reconnect_interval_seconds: float = Field(default=10.0, gt=0)
    ib_reconnect_backoff_max_seconds: float = Field(default=60.0, gt=0)

    auto_connect_on_startup: bool = True
    allow_paper_orders: bool = False
    allow_live_orders: bool = False
    max_order_quantity: float = Field(default=1000.0, gt=0)
    risk_max_trade_notional: float = Field(default=25000.0, gt=0)
    risk_max_position_notional: float = Field(default=50000.0, gt=0)
    risk_max_symbol_concentration_pct: float = Field(default=5.0, gt=0, le=100)
    risk_max_daily_new_exposure: float = Field(default=100000.0, gt=0)
    risk_max_open_orders_per_symbol: int = Field(default=4, ge=0)
    risk_block_delayed_market_orders: bool = True
    risk_max_market_spread_bps: float = Field(default=50.0, gt=0)
    risk_require_limit_for_wide_spread: bool = True
    risk_wide_spread_bps: float = Field(default=10.0, gt=0)
    risk_live_trade_notional: float = Field(default=10000.0, gt=0)
    risk_live_position_notional: float = Field(default=25000.0, gt=0)
    risk_live_symbol_concentration_pct: float = Field(default=2.5, gt=0, le=100)
    risk_live_daily_new_exposure: float = Field(default=25000.0, gt=0)
    risk_live_max_open_orders_per_symbol: int = Field(default=2, ge=0)
    risk_live_require_approval: bool = True
    risk_paper_approval_trade_notional: float = Field(default=15000.0, gt=0)
    risk_live_approval_trade_notional: float = Field(default=5000.0, gt=0)
    approval_ttl_seconds: int = Field(default=900, gt=0)
    data_dir: str = str((Path(__file__).resolve().parents[2] / "data/ib-bridge"))
    log_dir: str | None = None
    log_file_name: str = "ib-bridge.log"
    log_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    log_backup_count: int = Field(default=5, ge=1)
    database_path_paper: str | None = None
    database_path_live: str | None = None

    @field_validator("ib_port", "database_path_paper", "database_path_live", mode="before")
    @classmethod
    def normalize_optional_values(cls, value: object) -> object:
        if value in ("", None):
            return None
        return value

    def resolved_ib_port(self, mode: Literal["paper", "live"] | None = None) -> int:
        if self.ib_port is not None:
            return self.ib_port

        resolved_mode = mode
        if resolved_mode is None:
            resolved_mode = self.ib_preferred_mode if self.ib_target_mode == "auto" else self.ib_target_mode

        return self.ib_paper_port if resolved_mode == "paper" else self.ib_live_port

    def resolved_database_mode(self) -> Literal["paper", "live"]:
        if self.ib_target_mode == "paper":
            return "paper"
        if self.ib_target_mode == "live":
            return "live"
        return self.ib_preferred_mode

    def resolved_database_path(self, mode: Literal["paper", "live"] | None = None) -> str:
        resolved_mode = mode or self.resolved_database_mode()
        explicit = self.database_path_paper if resolved_mode == "paper" else self.database_path_live
        if explicit:
            return explicit
        return str(Path(self.data_dir) / f"trading-{resolved_mode}.sqlite3")

    def resolved_log_dir(self) -> str:
        if self.log_dir:
            return self.log_dir
        return str(Path(self.data_dir) / "logs")

    def resolved_log_path(self) -> str:
        return str(Path(self.resolved_log_dir()) / self.log_file_name)


@lru_cache
def get_settings() -> Settings:
    return Settings()
