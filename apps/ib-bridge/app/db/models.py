from __future__ import annotations

import json
from datetime import UTC, datetime

from peewee import BooleanField, CharField, DateTimeField, Model, TextField

from app.db.database_ref import database


class BaseModel(Model):
    class Meta:
        database = database


class AuditEventRecord(BaseModel):
    event_id = CharField(primary_key=True, max_length=64)
    event_type = CharField(max_length=128)
    created_at = DateTimeField()
    actor = CharField(max_length=256, null=True)
    requester = CharField(max_length=256, null=True)
    request_source = CharField(max_length=64, null=True)
    agent_id = CharField(max_length=128, null=True)
    run_id = CharField(max_length=128, null=True)
    strategy_id = CharField(max_length=128, null=True)
    symbol = CharField(max_length=64, null=True)
    order_id = CharField(max_length=64, null=True)
    client_request_id = CharField(max_length=128, null=True)
    approval_id = CharField(max_length=64, null=True)
    status = CharField(max_length=64, null=True)
    policy_decision = CharField(max_length=64, null=True)
    payload_json = TextField()

    class Meta:
        table_name = "audit_event_record"


class IdempotencyRecord(BaseModel):
    client_request_id = CharField(primary_key=True, max_length=128)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    response_json = TextField()

    class Meta:
        table_name = "idempotency_record"


class ApprovalMandateStore(BaseModel):
    mandate_id = CharField(primary_key=True, max_length=64)
    status = CharField(max_length=32)
    created_at = DateTimeField()
    expires_at = DateTimeField()
    instrument_type = CharField(max_length=32)
    target_mode = CharField(max_length=16)
    symbols_json = TextField()
    actions_json = TextField()
    max_order_notional = TextField()
    max_uses = CharField(max_length=32)
    uses_consumed = CharField(max_length=32)
    note = TextField(null=True)
    requester = CharField(max_length=256, null=True)
    approved_by = CharField(max_length=256, null=True)
    request_json = TextField(null=True)
    policy_decision = CharField(max_length=64, null=True)
    approval_required = BooleanField(null=True)
    guardrails_json = TextField(null=True)
    request_context_json = TextField()

    class Meta:
        table_name = "approval_mandate"


class OrderLifecycleRecord(BaseModel):
    event_id = CharField(primary_key=True, max_length=64)
    order_id = CharField(max_length=64, index=True)
    symbol = CharField(max_length=64, null=True)
    action = CharField(max_length=32, null=True)
    order_type = CharField(max_length=32, null=True)
    quantity = TextField(null=True)
    limit_price = TextField(null=True)
    stop_price = TextField(null=True)
    time_in_force = CharField(max_length=16, null=True)
    latest_status = CharField(max_length=64, null=True)
    client_request_id = CharField(max_length=128, null=True)
    source_event_type = CharField(max_length=128)
    updated_at = DateTimeField()
    payload_json = TextField()

    class Meta:
        table_name = "order_lifecycle_record"


class PositionSnapshotRecord(BaseModel):
    snapshot_id = CharField(primary_key=True, max_length=64)
    symbol = CharField(max_length=64, index=True)
    account = CharField(max_length=64, null=True)
    exchange = CharField(max_length=64, null=True)
    currency = CharField(max_length=16, null=True)
    position = TextField()
    average_cost = TextField(null=True)
    captured_at = DateTimeField()
    source = CharField(max_length=64)

    class Meta:
        table_name = "position_snapshot_record"


def dump_json(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=True, default=str)
