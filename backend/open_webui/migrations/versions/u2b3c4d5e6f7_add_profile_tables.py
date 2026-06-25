"""add document_profile and embedding_profile tables

Revision ID: u2b3c4d5e6f7
Revises: t1a2b3c4d5e6
Create Date: 2026-03-31

"""

import json
import time
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u2b3c4d5e6f7"
down_revision: Union[str, None] = "t1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_config_value(config_data: dict, path: str, default=None):
    """Read a dot-notation path from config data JSON."""
    parts = path.split(".")
    current = config_data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return default
        if current is None:
            return default
    return current


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "document_profile" not in tables:
        op.create_table(
            "document_profile",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text()),
            sa.Column("name", sa.Text()),
            sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("content_extraction_engine", sa.Text(), server_default=""),
            sa.Column(
                "pdf_extract_images", sa.Boolean(), server_default=sa.text("false")
            ),
            sa.Column("text_splitter", sa.Text(), server_default=""),
            sa.Column("chunk_size", sa.Integer(), server_default="1000"),
            sa.Column("chunk_overlap", sa.Integer(), server_default="100"),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger()),
            sa.Column("updated_at", sa.BigInteger()),
        )

    if "embedding_profile" not in tables:
        op.create_table(
            "embedding_profile",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text()),
            sa.Column("name", sa.Text()),
            sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("embedding_engine", sa.Text(), server_default=""),
            sa.Column(
                "embedding_model",
                sa.Text(),
                server_default="sentence-transformers/all-MiniLM-L6-v2",
            ),
            sa.Column("embedding_batch_size", sa.Integer(), server_default="1"),
            sa.Column("embedding_dimensions", sa.Integer(), server_default="0"),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.BigInteger()),
            sa.Column("updated_at", sa.BigInteger()),
        )

    # Seed default profiles from existing config
    config_row = conn.execute(
        sa.text("SELECT data FROM config ORDER BY id DESC LIMIT 1")
    ).fetchone()

    config_data = {}
    if config_row and config_row[0]:
        raw = config_row[0]
        config_data = json.loads(raw) if isinstance(raw, str) else raw

    now = int(time.time())
    system_user_id = "system"

    # Check if default document profile already exists
    existing_doc = conn.execute(
        sa.text("SELECT id FROM document_profile WHERE is_default = true LIMIT 1")
    ).fetchone()

    if not existing_doc:
        doc_id = str(uuid.uuid4())
        engine = _get_config_value(config_data, "rag.CONTENT_EXTRACTION_ENGINE", "")
        chunk_size = _get_config_value(config_data, "rag.chunk_size", 1000)
        chunk_overlap = _get_config_value(config_data, "rag.chunk_overlap", 100)
        text_splitter = _get_config_value(config_data, "rag.text_splitter", "")
        pdf_extract_images = _get_config_value(
            config_data, "rag.PDF_EXTRACT_IMAGES", False
        )

        doc_config = {
            "tika_server_url": _get_config_value(
                config_data, "rag.TIKA_SERVER_URL", ""
            ),
            "docling_server_url": _get_config_value(
                config_data, "rag.DOCLING_SERVER_URL", ""
            ),
            "document_intelligence_endpoint": _get_config_value(
                config_data, "rag.DOCUMENT_INTELLIGENCE_ENDPOINT", ""
            ),
            "document_intelligence_key": _get_config_value(
                config_data, "rag.DOCUMENT_INTELLIGENCE_KEY", ""
            ),
            "mistral_ocr_api_key": _get_config_value(
                config_data, "rag.MISTRAL_OCR_API_KEY", ""
            ),
            "document_ai_project_id": _get_config_value(
                config_data, "rag.DOCUMENT_AI_PROJECT_ID", ""
            ),
            "document_ai_location": _get_config_value(
                config_data, "rag.DOCUMENT_AI_LOCATION", ""
            ),
            "document_ai_processor_id": _get_config_value(
                config_data, "rag.DOCUMENT_AI_PROCESSOR_ID", ""
            ),
            "document_ai_processor_version": _get_config_value(
                config_data, "rag.DOCUMENT_AI_PROCESSOR_VERSION", ""
            ),
            "document_ai_service_account_key": _get_config_value(
                config_data, "rag.DOCUMENT_AI_SERVICE_ACCOUNT_KEY", ""
            ),
        }

        conn.execute(
            sa.text(
                "INSERT INTO document_profile "
                "(id, user_id, name, is_default, content_extraction_engine, "
                "pdf_extract_images, text_splitter, chunk_size, chunk_overlap, "
                "config, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, true, :engine, :pdf, :splitter, "
                ":chunk_size, :chunk_overlap, :config, :created_at, :updated_at)"
            ),
            {
                "id": doc_id,
                "user_id": system_user_id,
                "name": "Default",
                "engine": engine or "",
                "pdf": True if pdf_extract_images else False,
                "splitter": text_splitter or "",
                "chunk_size": chunk_size or 1000,
                "chunk_overlap": chunk_overlap or 100,
                "config": json.dumps(doc_config),
                "created_at": now,
                "updated_at": now,
            },
        )

    # Check if default embedding profile already exists
    existing_emb = conn.execute(
        sa.text("SELECT id FROM embedding_profile WHERE is_default = true LIMIT 1")
    ).fetchone()

    if not existing_emb:
        emb_id = str(uuid.uuid4())
        emb_engine = _get_config_value(config_data, "rag.embedding_engine", "")
        emb_model = _get_config_value(
            config_data,
            "rag.embedding_model",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        emb_batch = _get_config_value(config_data, "rag.embedding_batch_size", 1)
        emb_dims = _get_config_value(config_data, "rag.RAG_EMBEDDING_DIMENSIONS", 0)

        emb_config = {
            "openai_api_base_url": _get_config_value(
                config_data, "rag.OPENAI_API_BASE_URL", ""
            ),
            "openai_api_key": _get_config_value(config_data, "rag.OPENAI_API_KEY", ""),
            "ollama_base_url": _get_config_value(
                config_data, "rag.OLLAMA_BASE_URL", ""
            ),
            "ollama_api_key": _get_config_value(config_data, "rag.OLLAMA_API_KEY", ""),
            "azure_openai_api_base_url": _get_config_value(
                config_data, "rag.AZURE_OPENAI_API_BASE_URL", ""
            ),
            "azure_openai_api_key": _get_config_value(
                config_data, "rag.AZURE_OPENAI_API_KEY", ""
            ),
            "azure_openai_api_version": _get_config_value(
                config_data, "rag.AZURE_OPENAI_API_VERSION", ""
            ),
            "gemini_api_key": _get_config_value(config_data, "rag.GEMINI_API_KEY", ""),
            "vertex_ai_project_id": _get_config_value(
                config_data, "rag.VERTEX_AI_PROJECT_ID", ""
            ),
            "vertex_ai_location": _get_config_value(
                config_data, "rag.VERTEX_AI_LOCATION", "us-central1"
            ),
            "vertex_ai_service_account_key": _get_config_value(
                config_data, "rag.VERTEX_AI_SERVICE_ACCOUNT_KEY", ""
            ),
        }

        conn.execute(
            sa.text(
                "INSERT INTO embedding_profile "
                "(id, user_id, name, is_default, embedding_engine, "
                "embedding_model, embedding_batch_size, embedding_dimensions, "
                "config, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, true, :engine, :model, "
                ":batch, :dims, :config, :created_at, :updated_at)"
            ),
            {
                "id": emb_id,
                "user_id": system_user_id,
                "name": "Default",
                "engine": emb_engine or "",
                "model": emb_model or "sentence-transformers/all-MiniLM-L6-v2",
                "batch": emb_batch or 1,
                "dims": emb_dims or 0,
                "config": json.dumps(emb_config),
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    op.drop_table("embedding_profile")
    op.drop_table("document_profile")
