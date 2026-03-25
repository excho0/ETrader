from typing import Literal

from pydantic import BaseModel


class ReadinessResponse(BaseModel):
    status: str
    connected: bool
    target_mode: Literal["paper", "live", "auto"]
    connected_mode: Literal["paper", "live"] | None = None
    host: str
    port: int
    client_id: int
    managed_accounts: list[str] = []
    reconnect_state: str | None = None
    reconnect_interval_seconds: float | None = None
    approval_queue_count: int = 0
    recent_policy_blocks: list[str] = []
