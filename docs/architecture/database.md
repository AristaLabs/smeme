# Database Architecture

Database design patterns and decisions for the SMEme Platform.

## Database Technology

- **PostgreSQL 16+** - Required for JSONB and advanced features
- **Neon** - Serverless PostgreSQL platform
- **SQLModel** - SQLAlchemy 2.0 + Pydantic v2 integration
- **Alembic** - Schema migrations

## Core Tables

### Users

User accounts managed by FastAPI-Users:

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR NOT NULL UNIQUE,
    username VARCHAR NOT NULL UNIQUE,
    hashed_password VARCHAR NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    is_superuser BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### QNRs (Questionnaires)

Questionnaire metadata and graph structure:

```sql
CREATE TABLE qnrs (
    id UUID PRIMARY KEY,
    author_id UUID REFERENCES users(id),
    title VARCHAR NOT NULL,
    description TEXT,
    graph_data JSONB NOT NULL,          -- Complete graph structure
    is_public BOOLEAN DEFAULT FALSE,
    was_ever_public BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    version INTEGER DEFAULT 1,
    parent_qnr_id UUID REFERENCES qnrs(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Graph Data Structure:**
```json
{
  "nodes": [
    {
      "id": "node1",
      "type": "question",
      "data": {
        "text": "Question text?",
        "type": "radio",
        "options": ["Option 1", "Option 2"]
      }
    }
  ],
  "edges": [
    {
      "source": "node1",
      "target": "node2",
      "condition": "Option 1"
    }
  ],
  "metadata": {
    "title": "QNR Title",
    "domain": "finance"
  }
}
```

### QNR Sessions

User sessions with LangGraph checkpointing:

```sql
CREATE TABLE qnr_sessions (
    id UUID PRIMARY KEY,
    qnr_id UUID REFERENCES qnrs(id),
    user_id UUID REFERENCES users(id),
    thread_id VARCHAR NOT NULL,             -- LangGraph thread ID
    current_node_id VARCHAR,
    session_data JSONB DEFAULT '{}',        -- User responses
    completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Memos

AI-generated memos from completed sessions:

```sql
CREATE TABLE memos (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES qnr_sessions(id),
    user_id UUID REFERENCES users(id),
    title VARCHAR NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Design Patterns

### JSONB for Flexible Data

Using JSONB for:
- **QNR graph structure** - Dynamic nodes and edges
- **Session state** - LangGraph checkpoint data
- **Metadata** - Extensible without migrations

**Benefits:**
- No schema migrations for graph changes
- Fast JSON queries with GIN indexes
- Native PostgreSQL support

### Soft Deletes

Using `is_archived` instead of DELETE:
- Preserve user data
- Enable restore functionality
- Audit trail

### Versioning

QNRs use parent-child versioning:
- `parent_qnr_id` links to original
- `version` tracks version number
- Only one version public at a time

### Timestamps

All tables have:
- `created_at` - Record creation
- `updated_at` - Last modification

## Connection Pooling

Configured based on environment:

```python
# Development: 5 connections
# Staging: 10 connections
# Production: 20 connections

engine = create_async_engine(
    DATABASE_URL,
    pool_size=pool_size,
    max_overflow=0,
    pool_pre_ping=True,
    echo=debug
)
```

## LangGraph Integration

LangGraph checkpoints stored in PostgreSQL using `langgraph-checkpoint-postgres`:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

checkpointer = AsyncPostgresSaver(conn=connection)
```

**Tables:**
- `checkpoints` - Workflow state snapshots
- `checkpoint_writes` - State updates

## Indexes

Key indexes for performance:

```sql
-- QNRs
CREATE INDEX idx_qnrs_author ON qnrs(author_id);
CREATE INDEX idx_qnrs_public ON qnrs(is_public) WHERE is_public = TRUE;
CREATE INDEX idx_qnrs_parent ON qnrs(parent_qnr_id) WHERE parent_qnr_id IS NOT NULL;

-- Sessions  
CREATE INDEX idx_sessions_qnr ON qnr_sessions(qnr_id);
CREATE INDEX idx_sessions_user ON qnr_sessions(user_id);
CREATE INDEX idx_sessions_thread ON qnr_sessions(thread_id);

-- Memos
CREATE INDEX idx_memos_session ON memos(session_id);
CREATE INDEX idx_memos_user ON memos(user_id);
```

## Migrations

All schema changes via Alembic:

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

See [Migration Best Practices](../operations/migration-best-practices.md) for details.

## Naming Conventions

Enforced via `BaseSQLModel`:

```python
constraint_naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
```

**Benefits:**
- Predictable constraint names
- Easier migrations
- Better debugging

---

**See also:** [Data Schema](../reference/data-schema.md) | [Migration Guide](../operations/migration-best-practices.md)

