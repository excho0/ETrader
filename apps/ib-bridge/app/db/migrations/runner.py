from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Callable

from peewee import CharField, DateTimeField, Model
from playhouse.migrate import SqliteMigrator


@dataclass(slots=True)
class MigrationContext:
    database: object
    migrator: SqliteMigrator

    def table_columns(self, table: str) -> set[str]:
        try:
            return {column.name for column in self.database.get_columns(table)}
        except Exception:
            return set()

    def has_table(self, table: str) -> bool:
        try:
            return table in set(self.database.get_tables())
        except Exception:
            return False

    def rename_table_if_exists(self, old_name: str, new_name: str) -> None:
        if self.has_table(new_name) or not self.has_table(old_name):
            return
        from playhouse.migrate import migrate

        migrate(self.migrator.rename_table(old_name, new_name))

    def add_column_if_missing(self, table: str, column_name: str, field) -> None:
        if not self.has_table(table):
            return
        if column_name in self.table_columns(table):
            return
        from playhouse.migrate import migrate

        migrate(self.migrator.add_column(table, column_name, field))

    def drop_column_if_exists(self, table: str, column_name: str) -> None:
        if not self.has_table(table):
            return
        if column_name not in self.table_columns(table):
            return
        from playhouse.migrate import migrate

        migrate(self.migrator.drop_column(table, column_name))


@dataclass(slots=True)
class MigrationDefinition:
    migration_id: str
    upgrade: Callable[[MigrationContext], None]
    downgrade: Callable[[MigrationContext], None] | None = None


def migration(
    migration_id: str,
    *,
    downgrade: Callable[[MigrationContext], None] | None = None,
) -> Callable[[Callable[[MigrationContext], None]], MigrationDefinition]:
    def decorator(upgrade: Callable[[MigrationContext], None]) -> MigrationDefinition:
        return MigrationDefinition(
            migration_id=migration_id,
            upgrade=upgrade,
            downgrade=downgrade,
        )

    return decorator


class MigrationRecord(Model):
    migration_id = CharField(primary_key=True, max_length=128)
    applied_at = DateTimeField()

    class Meta:
        table_name = "schema_migration_record"
        database = None


MIGRATION_MODULES = [
    "app.db.migrations.001_initial",
    "app.db.migrations.002_audit_event_columns",
    "app.db.migrations.003_order_lifecycle",
    "app.db.migrations.004_position_snapshots",
    "app.db.migrations.005_audit_execution_context",
]


def run_migrations(database) -> None:
    MigrationRecord._meta.database = database
    database.create_tables([MigrationRecord], safe=True)
    _ensure_migration_record_schema(database)
    context = MigrationContext(database=database, migrator=SqliteMigrator(database))

    for definition in _load_migrations():
        if MigrationRecord.get_or_none(MigrationRecord.migration_id == definition.migration_id) is not None:
            continue
        definition.upgrade(context)
        MigrationRecord.create(
            migration_id=definition.migration_id,
            applied_at=_utcnow(),
        )


def rollback_migrations(database, steps: int = 1) -> list[str]:
    MigrationRecord._meta.database = database
    database.create_tables([MigrationRecord], safe=True)
    _ensure_migration_record_schema(database)
    context = MigrationContext(database=database, migrator=SqliteMigrator(database))
    applied = list(MigrationRecord.select().order_by(MigrationRecord.applied_at.desc()).limit(max(steps, 0)))
    definitions = {definition.migration_id: definition for definition in _load_migrations()}
    rolled_back: list[str] = []

    for record in applied:
        definition = definitions.get(record.migration_id)
        if definition is None or definition.downgrade is None:
            raise RuntimeError(f"Migration {record.migration_id} does not support rollback")
        definition.downgrade(context)
        record.delete_instance()
        rolled_back.append(record.migration_id)

    return rolled_back


def _load_migrations() -> list[MigrationDefinition]:
    definitions: list[MigrationDefinition] = []
    for module_name in MIGRATION_MODULES:
        module = import_module(module_name)
        definition = getattr(module, "MIGRATION", None)
        if not isinstance(definition, MigrationDefinition):
            raise TypeError(f"{module_name} must define MIGRATION = migration(...)(...)")
        definitions.append(definition)
    return definitions


def _utcnow():
    return datetime.now(UTC)


def _ensure_migration_record_schema(database) -> None:
    try:
        columns = {column.name for column in database.get_columns("schema_migration_record")}
    except Exception:
        columns = set()

    if "applied_at" in columns or not columns:
        return

    migrator = SqliteMigrator(database)
    from playhouse.migrate import migrate

    migrate(
        migrator.add_column(
            "schema_migration_record",
            "applied_at",
            DateTimeField(default=_utcnow),
        )
    )
    database.execute_sql(
        "UPDATE schema_migration_record SET applied_at = ? WHERE applied_at IS NULL",
        (_utcnow(),),
    )
