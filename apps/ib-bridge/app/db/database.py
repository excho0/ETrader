from __future__ import annotations

from pathlib import Path

from app.db.database_ref import database
from app.db.migrations.runner import run_migrations
from app.db.models import ApprovalRecordStore, AuditEventRecord, IdempotencyRecord, OrderLifecycleRecord, PositionSnapshotRecord


def initialize_database(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database.init(
        str(path),
        pragmas={
            "journal_mode": "wal",
            "cache_size": -64 * 1024,
            "foreign_keys": 1,
            "synchronous": 1,
        },
    )
    database.connect(reuse_if_open=True)
    run_migrations(database)
    database.create_tables(
        [AuditEventRecord, IdempotencyRecord, ApprovalRecordStore, OrderLifecycleRecord, PositionSnapshotRecord],
        safe=True,
    )
