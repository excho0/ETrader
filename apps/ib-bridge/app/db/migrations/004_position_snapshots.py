from __future__ import annotations

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    if context.has_table("position_snapshot_record"):
        context.database.execute_sql("DROP TABLE position_snapshot_record")


@migration("004_position_snapshots", downgrade=_downgrade)
def _upgrade(context: MigrationContext) -> None:
    if context.has_table("position_snapshot_record"):
        return
    context.database.execute_sql(
        """
        CREATE TABLE position_snapshot_record (
            snapshot_id VARCHAR(64) PRIMARY KEY,
            symbol VARCHAR(64) NOT NULL,
            account VARCHAR(64),
            exchange VARCHAR(64),
            currency VARCHAR(16),
            position TEXT NOT NULL,
            average_cost TEXT,
            captured_at DATETIME NOT NULL,
            source VARCHAR(64) NOT NULL
        )
        """
    )
    context.database.execute_sql(
        "CREATE INDEX IF NOT EXISTS position_snapshot_record_symbol_idx ON position_snapshot_record(symbol)"
    )


MIGRATION = _upgrade
