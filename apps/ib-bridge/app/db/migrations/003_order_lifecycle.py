from __future__ import annotations

from datetime import UTC, datetime

from peewee import CharField, DateTimeField, TextField

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    if context.has_table("order_lifecycle_record"):
        context.database.execute_sql("DROP TABLE order_lifecycle_record")


@migration("003_order_lifecycle", downgrade=_downgrade)
def _upgrade(context: MigrationContext) -> None:
    if context.has_table("order_lifecycle_record"):
        return
    context.database.execute_sql(
        """
        CREATE TABLE order_lifecycle_record (
            event_id VARCHAR(64) PRIMARY KEY,
            order_id VARCHAR(64) NOT NULL,
            symbol VARCHAR(64),
            action VARCHAR(32),
            order_type VARCHAR(32),
            quantity TEXT,
            limit_price TEXT,
            stop_price TEXT,
            time_in_force VARCHAR(16),
            latest_status VARCHAR(64),
            client_request_id VARCHAR(128),
            source_event_type VARCHAR(128) NOT NULL,
            updated_at DATETIME NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    context.database.execute_sql(
        "CREATE INDEX IF NOT EXISTS order_lifecycle_record_order_id_idx ON order_lifecycle_record(order_id)"
    )


MIGRATION = _upgrade
