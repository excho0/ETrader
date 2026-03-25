from __future__ import annotations

from peewee import CharField

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    context.drop_column_if_exists("audit_event_record", "strategy_id")
    context.drop_column_if_exists("audit_event_record", "run_id")
    context.drop_column_if_exists("audit_event_record", "agent_id")
    context.drop_column_if_exists("audit_event_record", "request_source")
    context.drop_column_if_exists("audit_event_record", "requester")


@migration("005_audit_execution_context", downgrade=_downgrade)
def _upgrade(context: MigrationContext) -> None:
    context.add_column_if_missing("audit_event_record", "requester", CharField(max_length=256, null=True))
    context.add_column_if_missing("audit_event_record", "request_source", CharField(max_length=64, null=True))
    context.add_column_if_missing("audit_event_record", "agent_id", CharField(max_length=128, null=True))
    context.add_column_if_missing("audit_event_record", "run_id", CharField(max_length=128, null=True))
    context.add_column_if_missing("audit_event_record", "strategy_id", CharField(max_length=128, null=True))


MIGRATION = _upgrade
