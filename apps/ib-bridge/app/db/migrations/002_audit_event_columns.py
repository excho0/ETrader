from __future__ import annotations

from peewee import CharField

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    context.drop_column_if_exists("audit_event_record", "policy_decision")
    context.drop_column_if_exists("audit_event_record", "status")
    context.drop_column_if_exists("audit_event_record", "approval_id")
    context.drop_column_if_exists("audit_event_record", "client_request_id")
    context.drop_column_if_exists("audit_event_record", "order_id")
    context.drop_column_if_exists("audit_event_record", "symbol")
    context.drop_column_if_exists("audit_event_record", "actor")


@migration("002_audit_event_columns", downgrade=_downgrade)
def _upgrade(context: MigrationContext) -> None:
    context.add_column_if_missing("audit_event_record", "actor", CharField(max_length=256, null=True))
    context.add_column_if_missing("audit_event_record", "symbol", CharField(max_length=64, null=True))
    context.add_column_if_missing("audit_event_record", "order_id", CharField(max_length=64, null=True))
    context.add_column_if_missing(
        "audit_event_record",
        "client_request_id",
        CharField(max_length=128, null=True),
    )
    context.add_column_if_missing("audit_event_record", "approval_id", CharField(max_length=64, null=True))
    context.add_column_if_missing("audit_event_record", "status", CharField(max_length=64, null=True))
    context.add_column_if_missing("audit_event_record", "policy_decision", CharField(max_length=64, null=True))


MIGRATION = _upgrade
