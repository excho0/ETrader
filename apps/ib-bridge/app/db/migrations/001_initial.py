from __future__ import annotations

from datetime import UTC, datetime

from peewee import CharField, DateTimeField

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    context.drop_column_if_exists("approval_record", "approved_by")
    context.drop_column_if_exists("approval_record", "requester")
    context.drop_column_if_exists("idempotency_record", "created_at")


@migration("001_initial", downgrade=_downgrade)
def _upgrade(context: MigrationContext) -> None:
    context.rename_table_if_exists("auditeventrecord", "audit_event_record")
    context.rename_table_if_exists("idempotencyrecord", "idempotency_record")
    context.rename_table_if_exists("approvalrecordstore", "approval_record")

    context.add_column_if_missing(
        "idempotency_record",
        "created_at",
        DateTimeField(default=datetime.now(UTC)),
    )
    context.add_column_if_missing(
        "approval_record",
        "requester",
        CharField(max_length=256, null=True),
    )
    context.add_column_if_missing(
        "approval_record",
        "approved_by",
        CharField(max_length=256, null=True),
    )


MIGRATION = _upgrade
