from app.db.models import ApprovalMandateStore

from app.db.migrations.runner import MigrationContext, migration


def _downgrade(context: MigrationContext) -> None:
    if context.has_table("approval_mandate"):
        ApprovalMandateStore._meta.database = context.database
        ApprovalMandateStore.drop_table(safe=True)


@migration("006_approval_mandates", downgrade=_downgrade)
def upgrade(context: MigrationContext) -> None:
    ApprovalMandateStore._meta.database = context.database
    ApprovalMandateStore.create_table(safe=True)


MIGRATION = upgrade
