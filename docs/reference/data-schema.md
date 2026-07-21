# Data Schema & Database Architecture

## Overview

This document provides a comprehensive overview of the smeme_v2 database schema, including all tables, relationships, constraints, and best practices for working with the data models.

**Last Updated**: February 2026  
**Database**: PostgreSQL 15+  
**ORM**: SQLModel (SQLAlchemy 2.0 + Pydantic V2)

---

## Table of Contents

1. [Schema Diagram](#schema-diagram)
2. [Core Tables](#core-tables)
3. [Relationship Definitions](#relationship-definitions)
4. [Cascade Rules & Delete Behavior](#cascade-rules--delete-behavior)
5. [Field Types & Conventions](#field-types--conventions)
6. [Indexes & Performance](#indexes--performance)
7. [Working with the ORM](#working-with-the-orm)
8. [Common Patterns](#common-patterns)
9. [Migration Guidelines](#migration-guidelines)
10. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)

---

## Schema Diagram

```
┌─────────────┐
│    User     │
│  (users)    │
└──────┬──────┘
       │
       │ 1:N (author)
       │
       ↓
┌─────────────┐
│     QNR     │
│   (qnrs)    │
└──────┬──────┘
       │
       │ 1:N
       │ cascade="all, delete-orphan"
       ↓
┌─────────────┐
│ QNRSession  │
│(qnr_sessions)│
└──────┬──────┘
       │
       │ 1:N
       │ cascade="all, delete-orphan"
       ↓
┌─────────────┐
│    Memo     │
│  (memos)    │
└─────────────┘
```

### Relationship Summary

- **User → QNR**: One user (author) can create many QNRs
- **QNR → QNRSession**: One QNR can have many user sessions (different users completing it)
- **QNRSession → Memo**: One session can generate many memos (though typically 1:1)
- **User → QNRSession**: One user can have many sessions (for different QNRs)
- **User → Memo**: One user can have many memos (from their various sessions)

---

## Core Tables

### 1. User (`users`)

**Purpose**: Stores user accounts and authentication data (managed by FastAPI-Users).

**Primary Key**: `id` (UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `uuid4()` | Primary key |
| `email` | String | No | - | Unique email address |
| `username` | String(255) | No | - | Unique internal slug (derived from email local-part at Clerk sync; not Clerk username; editable public aliases planned for Business tier) |
| `hashed_password` | String | No | - | Bcrypt hashed password |
| `is_active` | Boolean | No | `True` | Account active status |
| `is_superuser` | Boolean | No | `False` | Admin privileges |
| `is_verified` | Boolean | No | `False` | Email verification status |
| `created_at` | DateTime(tz) | No | `now()` | Account creation time |
| `updated_at` | DateTime(tz) | No | `now()` | Last update time |

**Indexes**:
- Primary: `id`
- Unique: `email`, `username`

**Relationships**:
- Has many QNRs (as author)
- Has many QNRSessions (as participant)
- Has many Memos (as owner)

**Model Location**: `smeme/core/models.py::User`

---

### 2. QNR (`qnrs`)

**Purpose**: Stores questionnaire definitions (graph structure, metadata).

**Primary Key**: `id` (UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `uuid4()` | Primary key |
| `author_id` | UUID | Yes | `None` | Foreign key → `users.id` |
| `title` | String | No | - | QNR display name |
| `graph_data` | JSONB | No | - | Nodes, edges, metadata |
| `is_public` | Boolean | No | `False` | Public visibility (private by default) |
| `was_ever_public` | Boolean | No | `False` | True if QNR was ever made public |
| `is_archived` | Boolean | No | `False` | Soft delete flag |
| `archived_at` | DateTime(tz) | Yes | `None` | When this QNR was archived (soft deleted) |
| `version_number` | Integer | No | `1` | Incremental version number |
| `parent_qnr_id` | UUID | Yes | `None` | Foreign key to parent version |
| `is_current` | Boolean | No | `True` | Is this the current version? |
| `created_at` | DateTime(tz) | No | `now()` | Creation time |
| `updated_at` | DateTime(tz) | No | `now()` | Last update time |

**Indexes**:
- Primary: `id`
- Index: `title`, `is_public`, `is_archived`, `is_current`
- Foreign key index: `author_id`, `parent_qnr_id`

**Relationships**:
- Belongs to one User (author)
- Has many QNRSessions (no cascade - sessions are user data and survive QNR deletion)

**JSONB Structure** (`graph_data`):
```json
{
  "nodes": [
    {
      "id": "q1",
      "type": "question",
      "data": {
        "text": "What is your name?",
        "type": "text",
        "options": null,
        "placeholder": "Enter your full name",
        "required": true,
        "help_text": "Enter your full name"
      }
    },
    {
      "id": "conclusion_1",
      "type": "conclusion",
      "data": {
        "title": "Recommendation",
        "summary": "Based on your answers...",
        "recommendations": "Next steps...",
        "severity": "info"
      }
    }
  ],
  "edges": [
    {
      "source": "q1",
      "target": "conclusion_1",
      "condition": null
    }
  ],
  "start_node": "q1",
  "metadata": {
    "title": "Sample Questionnaire",
    "description": "A sample QNR",
    "category": "general",
    "estimated_time": 5,
    "version": "1.0.0",
    "tags": ["sample"]
  }
}
```

**Model Location**: `smeme/core/models.py::QNR`

---

### 3. QNRSession (`qnr_sessions`)

**Purpose**: Tracks a user's progress through a specific QNR.

**Primary Key**: `id` (UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `uuid4()` | Primary key |
| `user_id` | UUID | No | - | Foreign key → `users.id` |
| `qnr_id` | UUID | No | - | Foreign key → `qnrs.id` |
| `current_node_id` | String | Yes | `None` | Current question ID |
| `user_responses` | JSONB | No | `{}` | User answers by node ID |
| `conclusion_reached` | String | Yes | `None` | ID of the conclusion node reached (if any) |
| `started_at` | DateTime(tz) | Yes | `None` | When user started the QNR (first answer) |
| `completed_at` | DateTime(tz) | Yes | `None` | Completion timestamp |
| `created_at` | DateTime(tz) | No | `now()` | Creation time |
| `updated_at` | DateTime(tz) | No | `now()` | Last update time |

**Indexes**:
- Primary: `id`
- Index: `user_id`, `qnr_id`

**Relationships**:
- Belongs to one User
- Belongs to one QNR
- Has many Memos (cascade delete)

**JSONB Structure** (`user_responses`):
```json
{
  "q1": "John Doe",
  "q2": "Software Engineer",
  "q3": ["Python", "JavaScript", "Go"]
}
```

**Model Location**: `smeme/core/models.py::QNRSession`

---

### 4. UserQNRSession (`user_qnr_sessions`) — Sprint 8

**Purpose**: Tracks session count per user per QNR for first-free logic and revenue attribution.

**Primary Key**: `(user_id, qnr_id)` (composite)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `user_id` | UUID | No | - | Foreign key → `users.id` |
| `qnr_id` | UUID | No | - | Foreign key → `qnrs.id` |
| `first_session_id` | UUID | Yes | `None` | Foreign key → `qnr_sessions.id` (earliest session) |
| `session_count` | Integer | No | `0` | Total sessions for this user+QNR |
| `created_at` | DateTime(tz) | No | `now()` | Creation time |
| `updated_at` | DateTime(tz) | No | `now()` | Last update time |

**Indexes**:
- Primary: `(user_id, qnr_id)`
- Foreign keys: `user_id`, `qnr_id`, `first_session_id`

**Relationships**:
- Belongs to one User
- Belongs to one QNR
- References one QNRSession (first_session_id)

**Model Location**: `smeme/core/models.py::UserQNRSession`

---

### 5. Memo (`memos`)

**Purpose**: Stores AI-generated memos from completed QNR sessions.

**Primary Key**: `id` (UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `uuid4()` | Primary key |
| `session_id` | UUID | No | - | Foreign key → `qnr_sessions.id` |
| `user_id` | UUID | No | - | Foreign key → `users.id` |
| `title` | String(500) | No | - | Memo title |
| `summary` | Text | No | - | Memo summary |
| `recommendations` | Text | No | - | AI recommendations |
| `llm_response` | JSONB | No | `{}` | Raw LLM output (debug) |
| `generated_at` | DateTime(tz) | No | `now()` | Generation timestamp |

**Indexes**:
- Primary: `id`
- Index: `session_id`, `user_id`

**Relationships**:
- Belongs to one QNRSession
- Belongs to one User

**Model Location**: `smeme/core/models.py::Memo`

---

## Relationship Definitions

### Why Explicit Relationships?

SQLAlchemy relationships provide:
1. **Schema visibility**: See data dependencies at a glance
2. **Automatic cascades**: Delete parent → children deleted automatically
3. **Type safety**: IDE autocomplete for related objects
4. **Lazy loading**: Control when related data is fetched
5. **Prevention of bugs**: No manual cascade logic = no foreign key violations

### Relationship Syntax

```python
from sqlalchemy.orm import Mapped, relationship

# Parent model
class QNR(SQLModel, table=True):
    # ... fields ...
    
    # Relationship definition
    sessions: Mapped[list["QNRSession"]] = relationship(
        "QNRSession",              # Related model class name
        back_populates="qnr",      # Name of reverse relationship
        cascade="all, delete-orphan",  # Cascade behavior
        lazy="selectin",           # Loading strategy
    )

# Child model
class QNRSession(SQLModel, table=True):
    # ... fields ...
    
    # Reverse relationship
    qnr: Mapped["QNR"] = relationship(
        "QNR",
        back_populates="sessions"  # Must match parent's relationship name
    )
```

### `back_populates` Matching Rule

The `back_populates` parameter must **exactly match** the relationship attribute name on the other model:

```python
# ✅ CORRECT - Names match
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="qnr"  # ← Matches QNRSession.qnr
    )

class QNRSession:
    qnr: Mapped["QNR"] = relationship(
        back_populates="sessions"  # ← Matches QNR.sessions
    )

# ❌ WRONG - Names don't match
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="parent_qnr"  # ← QNRSession has no such attribute!
    )
```

### Complete Relationship Map

```python
# QNR → QNRSession
QNR.sessions: Mapped[list["QNRSession"]] = relationship(
    "QNRSession",
    back_populates="qnr",
    cascade="all, delete-orphan",  # Delete QNR → cascade to sessions
    lazy="selectin",
)

# QNRSession → QNR (reverse)
QNRSession.qnr: Mapped["QNR"] = relationship(
    "QNR",
    back_populates="sessions"
)

# QNRSession → Memo
QNRSession.memos: Mapped[list["Memo"]] = relationship(
    "Memo",
    back_populates="session",
    cascade="all, delete-orphan",  # Delete session → cascade to memos
    lazy="selectin",
)

# Memo → QNRSession (reverse)
Memo.session: Mapped["QNRSession"] = relationship(
    "QNRSession",
    back_populates="memos"
)
```

---

## Cascade Rules & Delete Behavior

### Understanding Cascade Options

| Cascade Rule | Behavior | Use Case |
|--------------|----------|----------|
| `all` | Propagate all operations | Standard for parent-child |
| `delete` | Propagate delete only | When children should be deleted |
| `delete-orphan` | Delete orphaned children | When children can't exist alone |
| `save-update` | Propagate add/update | Standard for most relationships |
| `merge` | Propagate merge operations | Session management |

### Our Cascade Configuration

```python
# QNR → QNRSession: NO CASCADE
# Effect: Sessions are user data and survive QNR deletion
# Note: Sessions remain tied to the specific QNR version they were started with
# Relationship configured with lazy="raise" to prevent accidental loads

# QNRSession → Memo: "all, delete-orphan"
# Effect: Deleting a session automatically deletes all its memos
cascade="all, delete-orphan"
```

### Delete Flow Example

When you delete a QNR:

```python
# Delete a QNR
qnr = await db.get(QNR, qnr_id)
await db.delete(qnr)
await db.commit()

# SQLAlchemy behavior:
# - QNR is deleted
# - QNRSessions remain (orphaned but preserved - they contain user data)
# - If you need to delete sessions, you must do so explicitly
```

When you delete a QNRSession:

```python
# Delete a session
session = await db.get(QNRSession, session_id)
await db.delete(session)
await db.commit()

# SQLAlchemy automatically:
# 1. Finds all Memo records with session_id = session.id
# 2. Deletes Memos first (leaf nodes)
# 3. Finally deletes QNRSession (root node)
# All in the correct order to satisfy foreign key constraints!
```

**Note**: For QNR → QNRSession, there is NO cascade. Sessions are preserved when QNRs are deleted because they contain user data. If you need to delete sessions, you must do so explicitly.

**Example with cascade** (QNRSession → Memo):
```python
# ✅ ORM cascade - clean, safe, automatic
# Deleting a session automatically deletes its memos
session = await db.get(QNRSession, session_id)
await db.delete(session)
await db.commit()
# Memos are automatically deleted via cascade
```

### Cascade Best Practices

1. **Use `delete-orphan` for dependent children**
   - Children that cannot exist without parent (Memo without QNRSession)
   
2. **Don't cascade to independent entities**
   - User should NOT cascade to QNR (users can exist without their QNRs)
   
3. **Test cascade behavior**
   - Always verify deletions cascade correctly in development
   
4. **Log cascade operations**
   - Include context about what will be deleted in logs

---

## Field Types & Conventions

### Standard Field Types

| Python Type | PostgreSQL Type | Use Case |
|------------|----------------|----------|
| `UUID` | `UUID` | Primary keys, foreign keys |
| `str` | `VARCHAR` | Short text (titles, names) |
| `str` | `TEXT` | Long text (summaries, descriptions) |
| `dict[str, Any]` | `JSONB` | Structured data, flexible schemas |
| `bool` | `BOOLEAN` | Flags, status indicators |
| `datetime` | `TIMESTAMP WITH TIME ZONE` | All timestamps |
| `int` | `INTEGER` | Counters, quantities |

### Field Definition Template

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4
import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, relationship
from sqlmodel import Field, SQLModel

class MyModel(SQLModel, table=True):
    """Model description."""
    
    model_config = {"arbitrary_types_allowed": True}  # ← Always first
    
    __tablename__ = "my_models"  # ← Always second
    
    # Primary key
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Foreign keys (always indexed)
    parent_id: UUID = Field(foreign_key="parents.id", index=True)
    
    # String fields
    title: str = Field(max_length=500, nullable=False)
    
    # Text fields (no length limit)
    description: str = Field(sa_column=Column(Text, nullable=False))
    
    # JSONB fields
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    
    # Timestamps (always timezone-aware with Mapped)
    created_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
        )
    )
    
    updated_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        )
    )
    
    # Relationships (always at the end)
    children: Mapped[list["ChildModel"]] = relationship(
        "ChildModel",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
```

### Critical Conventions

1. **Always use `Mapped[datetime]` for timestamp fields**
   ```python
   # ✅ CORRECT
   created_at: Mapped[datetime] = Field(...)
   
   # ❌ WRONG
   created_at: datetime = Field(...)
   ```

2. **Always use timezone-aware datetimes**
   ```python
   # ✅ CORRECT
   from datetime import UTC, datetime
   default_factory=lambda: datetime.now(UTC)
   
   # ❌ WRONG (naive datetime)
   default_factory=datetime.now
   ```

3. **Always use JSONB for PostgreSQL (not JSON)**
   ```python
   # ✅ CORRECT (better performance)
   sa_column=Column(JSONB)
   
   # ❌ WRONG (slower, fewer features)
   sa_column=Column(JSON)
   ```

4. **Always import UUID from stdlib (not sqlalchemy)**
   ```python
   # ✅ CORRECT
   from uuid import UUID, uuid4
   
   # ❌ WRONG
   from sqlalchemy.dialects.postgresql import UUID
   ```

---

## Indexes & Performance

### Current Indexes

**Primary Keys** (automatic unique index):
- `users.id`
- `qnrs.id`
- `qnr_sessions.id`
- `memos.id`

**Foreign Keys** (explicit index):
- `qnrs.author_id`
- `qnr_sessions.user_id`
- `qnr_sessions.qnr_id`
- `memos.session_id`
- `memos.user_id`

**Query Optimization Indexes**:
- `qnrs.title` (for search)
- `qnrs.status` (for filtering by status)

### Index Best Practices

1. **Always index foreign keys**
   - Speeds up joins significantly
   - Enable with `index=True` in Field definition

2. **Index frequently queried fields**
   - Status columns (draft/published)
   - User-facing search fields (title)

3. **Don't over-index**
   - Each index slows down writes
   - Profile queries before adding indexes

4. **Use composite indexes for multi-column queries**
   ```python
   # If you often query: WHERE user_id = X AND status = Y
   __table_args__ = (
       sa.Index('idx_user_status', 'user_id', 'status'),
   )
   ```

---

## Working with the ORM

### Loading Related Data

**Lazy Loading** (default - N+1 problem):
```python
# ❌ Causes N+1 queries
qnr = await db.get(QNR, qnr_id)
for session in qnr.sessions:  # Each iteration hits DB
    print(session.user_id)
```

**Eager Loading** (configured in relationship):
```python
# ✅ Single query with JOIN
# In model: lazy="selectin"
qnr = await db.get(QNR, qnr_id)
for session in qnr.sessions:  # Already loaded
    print(session.user_id)
```

**Explicit Eager Loading** (query-time):
```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(QNR)
    .options(selectinload(QNR.sessions))
    .where(QNR.id == qnr_id)
)
qnr = result.scalar_one()
```

### Creating Records with Relationships

```python
# Create parent and children together
qnr = QNR(
    title="Career Assessment",
    graph_data={"nodes": [...], "edges": [...]},
    author_id=user.id
)

# Sessions will cascade automatically on save
db.add(qnr)
await db.commit()
await db.refresh(qnr)  # Load generated ID

# Create child with parent reference
session = QNRSession(
    user_id=user.id,
    qnr_id=qnr.id,  # Foreign key
    current_node_id="q1"
)
db.add(session)
await db.commit()

# Or via relationship
qnr.sessions.append(session)
await db.commit()
```

### Deleting with Cascades

```python
# Delete parent → children automatically deleted
qnr = await db.get(QNR, qnr_id)
await db.delete(qnr)
await db.commit()
# All sessions and their memos are gone!

# Delete child → parent unaffected
session = await db.get(QNRSession, session_id)
await db.delete(session)
await db.commit()
# QNR remains, only session and its memos deleted
```

### Accessing Related Data

```python
# Access via relationship attribute
qnr = await db.get(QNR, qnr_id)

# Get all sessions (loaded via lazy="selectin")
sessions = qnr.sessions

# Get first session's memos
if sessions:
    memos = sessions[0].memos
    
# Navigate back to parent
if memos:
    session = memos[0].session
    qnr = session.qnr
```

---

## Common Patterns

### Pattern 1: User Dashboard (List User's QNRs)

```python
from sqlalchemy import select

# Get user's QNRs with session counts
result = await db.execute(
    select(QNR)
    .where(QNR.author_id == user.id)
    .where(QNR.status != "archived")
    .order_by(QNR.updated_at.desc())
)
my_qnrs = list(result.scalars().all())

# Access sessions via relationship
for qnr in my_qnrs:
    session_count = len(qnr.sessions)
    print(f"{qnr.title}: {session_count} sessions")
```

### Pattern 2: Session Progress

```python
# Get session with QNR and memos
result = await db.execute(
    select(QNRSession)
    .options(
        selectinload(QNRSession.qnr),
        selectinload(QNRSession.memos)
    )
    .where(QNRSession.id == session_id)
)
session = result.scalar_one()

# Check completion
is_complete = session.completed_at is not None
has_memo = len(session.memos) > 0
```

### Pattern 3: Safe Delete with Authorization

```python
# Load with authorization check
qnr = await db.get(QNR, qnr_id)
if not qnr:
    raise HTTPException(status_code=404, detail="QNR not found")

if qnr.author_id != user.id:
    raise HTTPException(status_code=403, detail="Not authorized")

# Log before delete
logger.info(
    f"Deleting QNR: {qnr.title}",
    extra={
        "qnr_id": str(qnr_id),
        "session_count": len(qnr.sessions),
        "user_id": str(user.id)
    }
)

# ORM handles cascades
await db.delete(qnr)
await db.commit()
```

### Pattern 4: Atomic Update of JSONB

```python
from sqlalchemy import update, func
from sqlalchemy.dialects.postgresql import JSONB

# Atomic JSONB update (avoids race conditions)
stmt = (
    update(QNRSession)
    .where(QNRSession.id == session_id)
    .values(
        user_responses=func.jsonb_set(
            QNRSession.user_responses,
            f'{{{question_id}}}',
            func.to_jsonb(answer),
            True  # Create if not exists
        ),
        updated_at=func.now()
    )
)
await db.execute(stmt)
await db.commit()
```

---

## Migration Guidelines

### Creating Migrations

```bash
# Generate migration from model changes
uv run alembic revision --autogenerate -m "Add QNR relationships"

# Review generated file in alembic/versions/
# IMPORTANT: Alembic cannot serialize `default_factory` or `AutoString`!

# Manual fixes needed in migration file:
# 1. Remove default_factory from timestamps, keep only server_default
# 2. Change AutoString to sa.String(length=X)
```

### Migration Best Practices

1. **Review before applying**
   - Always read the generated migration
   - Check for data loss operations (DROP, ALTER)

2. **Test migrations**
   - Apply on development database first
   - Verify data integrity after migration

3. **Handle data migrations**
   - Use `op.execute()` for data transformations
   - Add both upgrade and downgrade logic

4. **Backup before production migrations**
   ```bash
   # Backup production database
   pg_dump smeme_production > backup_$(date +%Y%m%d).sql
   
   # Apply migration
   uv run alembic upgrade head
   ```

### Common Migration Operations

**Add relationship (no schema change)**:
```python
# No migration needed! Relationships are Python-only.
# The foreign key already exists in the database.
```

**Add cascade to existing foreign key**:
```python
# In migration file
def upgrade():
    op.drop_constraint('memos_session_id_fkey', 'memos')
    op.create_foreign_key(
        'memos_session_id_fkey',
        'memos', 'qnr_sessions',
        ['session_id'], ['id'],
        ondelete='CASCADE'  # ← Add cascade
    )
```

**Add new model**:
```python
# alembic revision --autogenerate will detect new table
# Review and apply
uv run alembic upgrade head
```

---

## Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Manual Cascade Deletes

```python
# ❌ DON'T DO THIS
session_ids = await db.execute(
    select(QNRSession.id).where(QNRSession.qnr_id == qnr_id)
)
for session_id in session_ids:
    await db.execute(delete(Memo).where(Memo.session_id == session_id))
await db.execute(delete(QNRSession).where(QNRSession.qnr_id == qnr_id))
await db.delete(qnr)
await db.commit()

# ✅ DO THIS
await db.delete(qnr)  # Cascades automatically
await db.commit()
```

### ❌ Anti-Pattern 2: Forgetting to Define Relationships

```python
# ❌ Missing relationships
class QNR(SQLModel, table=True):
    id: UUID = Field(primary_key=True)
    # No sessions relationship = no cascade!

# ✅ Define relationships
class QNR(SQLModel, table=True):
    id: UUID = Field(primary_key=True)
    sessions: Mapped[list["QNRSession"]] = relationship(...)
```

### ❌ Anti-Pattern 3: Mismatched `back_populates`

```python
# ❌ Names don't match
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="parent_qnr"  # ← Wrong name
    )

class QNRSession:
    qnr: Mapped["QNR"] = relationship(
        back_populates="sessions"  # ← Mismatch!
    )

# ✅ Names match exactly
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="qnr"  # ← Matches QNRSession.qnr
    )

class QNRSession:
    qnr: Mapped["QNR"] = relationship(
        back_populates="sessions"  # ← Matches QNR.sessions
    )
```

### ❌ Anti-Pattern 4: Using Naive Datetimes

```python
# ❌ Naive datetime (no timezone)
from datetime import datetime
created_at = datetime.now()

# ✅ Timezone-aware datetime
from datetime import UTC, datetime
created_at = datetime.now(UTC)
```

### ❌ Anti-Pattern 5: Not Indexing Foreign Keys

```python
# ❌ Slow joins
qnr_id: UUID = Field(foreign_key="qnrs.id")

# ✅ Fast joins
qnr_id: UUID = Field(foreign_key="qnrs.id", index=True)
```

### ❌ Anti-Pattern 6: N+1 Query Problem

```python
# ❌ N+1 queries (one for QNR, N for sessions)
qnrs = await db.execute(select(QNR))
for qnr in qnrs.scalars():
    for session in qnr.sessions:  # Each triggers a query!
        print(session.id)

# ✅ Single query with eager loading
qnrs = await db.execute(
    select(QNR).options(selectinload(QNR.sessions))
)
for qnr in qnrs.scalars():
    for session in qnr.sessions:  # Already loaded
        print(session.id)
```

---

## Quick Reference

### Model Definition Checklist

- [ ] `model_config = {"arbitrary_types_allowed": True}` first
- [ ] `__tablename__ = "table_name"` second
- [ ] UUID primary key with `default_factory=uuid4`
- [ ] Foreign keys with `index=True`
- [ ] Timezone-aware timestamps with `Mapped[datetime]`
- [ ] JSONB for structured data (not JSON)
- [ ] Relationships at the end with correct `back_populates`
- [ ] Cascade rules for parent-child relationships

### Relationship Checklist

- [ ] Import `relationship` from `sqlalchemy.orm`
- [ ] Use `Mapped[list["ChildModel"]]` for one-to-many
- [ ] Use `Mapped["ParentModel"]` for many-to-one
- [ ] Set `back_populates` to match reverse relationship name
- [ ] Set `cascade="all, delete-orphan"` for dependent children
- [ ] Set `lazy="selectin"` to avoid N+1 queries
- [ ] Define on BOTH sides of the relationship

### Delete Operation Checklist

- [ ] Load object with `await db.get(Model, id)`
- [ ] Verify authorization (check ownership)
- [ ] Log deletion with context
- [ ] Use `await db.delete(obj)` (not SQL DELETE)
- [ ] Commit with `await db.commit()`
- [ ] Trust cascade rules to handle children

---

## Related Documentation

- [LangGraph Integration Guide](./LANGGRAPH_INTEGRATION_GUIDE.md) - See "Database Models & Migrations" section
- [QNR Editor Refactor Summary](./QNR_EDITOR_REFACTOR_SUMMARY.md) - Pydantic patterns
- [General Notes](./GENERAL_NOTES.MD) - Project-wide conventions

---

**Last Updated**: November 2025  
**Maintainer**: Development Team  
**Review Cycle**: Update when schema changes or patterns emerge

