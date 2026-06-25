from alembic import op
from open_webui.env import DATABASE_SCHEMA
from sqlalchemy import Inspector


def get_existing_tables():
    con = op.get_bind()
    inspector = Inspector.from_engine(con)
    tables = set(inspector.get_table_names(schema=DATABASE_SCHEMA or None))
    return tables


def get_revision_id():
    import uuid

    return str(uuid.uuid4()).replace("-", "")[:12]
