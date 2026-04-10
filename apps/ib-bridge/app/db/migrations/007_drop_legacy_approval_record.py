import json

from peewee import BooleanField, CharField, DateTimeField, Model, TextField

from app.db.models import ApprovalMandateStore

from app.db.migrations.runner import MigrationContext, migration


class _LegacyApprovalRecordStore(Model):
    approval_id = CharField(primary_key=True, max_length=64)
    status = CharField(max_length=32)
    created_at = DateTimeField()
    expires_at = DateTimeField()
    request_json = TextField()
    policy_decision = CharField(max_length=64)
    approval_required = BooleanField()
    guardrails_json = TextField()
    note = TextField(null=True)
    requester = CharField(max_length=256, null=True)
    approved_by = CharField(max_length=256, null=True)

    class Meta:
        table_name = "approval_record"
        database = None


def _downgrade(context: MigrationContext) -> None:
    return None


@migration("007_drop_legacy_approval_record", downgrade=_downgrade)
def upgrade(context: MigrationContext) -> None:
    if not context.has_table("approval_record"):
        return
    _LegacyApprovalRecordStore._meta.database = context.database
    ApprovalMandateStore._meta.database = context.database

    if context.has_table("approval_mandate"):
        for row in _LegacyApprovalRecordStore.select():
            try:
                request_payload = json.loads(row.request_json)
            except Exception:
                request_payload = {}
            instrument_type = str(request_payload.get("instrument_type") or "stock")
            symbol = request_payload.get("symbol")
            action = request_payload.get("action")
            request_context = {
                "requester": row.requester,
                "request_source": request_payload.get("request_source"),
                "agent_id": request_payload.get("agent_id"),
                "run_id": request_payload.get("run_id"),
                "strategy_id": request_payload.get("strategy_id"),
                "migrated_from": "approval_record",
            }

            ApprovalMandateStore.insert(
                mandate_id=row.approval_id,
                status="consumed" if row.status == "submitted" else row.status,
                created_at=row.created_at,
                expires_at=row.expires_at,
                instrument_type=instrument_type,
                target_mode=str(request_payload.get("target_mode") or request_payload.get("mode") or "auto"),
                symbols_json=json.dumps({"symbols": [symbol.upper()]} if isinstance(symbol, str) and symbol else {"symbols": []}),
                actions_json=json.dumps({"actions": [action.upper()]} if isinstance(action, str) and action else {"actions": []}),
                max_order_notional=str(
                    (
                        json.loads(row.guardrails_json).get("estimated_notional")
                        if row.guardrails_json
                        else None
                    )
                    or request_payload.get("limit_price")
                    or request_payload.get("entry_limit_price")
                    or request_payload.get("quantity")
                    or 1
                ),
                max_uses="1",
                uses_consumed="1" if row.status in {"submitted", "consumed"} else "0",
                note=row.note,
                requester=row.requester,
                approved_by=row.approved_by,
                request_json=row.request_json,
                policy_decision=row.policy_decision,
                approval_required=row.approval_required,
                guardrails_json=row.guardrails_json,
                request_context_json=json.dumps(request_context),
            ).on_conflict_ignore().execute()

    _LegacyApprovalRecordStore.drop_table(safe=True)


MIGRATION = upgrade
