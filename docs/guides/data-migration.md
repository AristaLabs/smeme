# Data Migration Guide

**Safe patterns for migrating data with Alembic + PostgreSQL**

---

## Overview

**Schema migrations** change table structure (add columns, indexes, constraints).  
**Data migrations** change the data itself (backfill, transform, cleanup).

This guide focuses on **data migrations** - how to safely modify existing data during deployments.

---

## Table of Contents

1. [Schema vs Data Migrations](#schema-vs-data-migrations)
2. [Common Patterns](#common-patterns)
3. [Safe Practices](#safe-practices)
4. [Zero-Downtime Strategies](#zero-downtime-strategies)
5. [Testing Data Migrations](#testing-data-migrations)
6. [Examples](#examples)
7. [Troubleshooting](#troubleshooting)

---

## Schema vs Data Migrations

### Schema Migration (DDL)

**What**: Change table structure  
**How**: Alembic autogenerate  
**Speed**: Usually instant (PostgreSQL metadata change)  
**Risk**: Low (reversible via downgrade)

```python
# Example: Add column
def upgrade() -> None:
    op.add_column('users', 
        sa.Column('bio', sa.String(), 
                  server_default='', 
                  nullable=False))
```

### Data Migration (DML)

**What**: Change actual data in rows  
**How**: Manual SQL in migration file  
**Speed**: Depends on table size (can be slow)  
**Risk**: Higher (data transformation, potential loss)

```python
# Example: Backfill data
def upgrade() -> None:
    # First add column (schema)
    op.add_column('users', 
        sa.Column('full_name', sa.String(), nullable=True))
    
    # Then backfill data (data migration)
    op.execute("""
        UPDATE users 
        SET full_name = username 
        WHERE full_name IS NULL
    """)
```

---

## Common Patterns

### 1. Backfill New Column from Existing Data

**Use case**: Add derived field from existing columns

```python
def upgrade() -> None:
    # Add column as nullable first
    op.add_column('qnrs', 
        sa.Column('slug', sa.String(), nullable=True))
    op.create_index('ix_qnrs_slug', 'qnrs', ['slug'])
    
    # Backfill: Generate slug from title
    op.execute("""
        UPDATE qnrs 
        SET slug = LOWER(REGEXP_REPLACE(title, '[^a-zA-Z0-9]+', '-', 'g'))
        WHERE slug IS NULL
    """)
    
    # Make NOT NULL after backfill (optional, can do later)
    # op.alter_column('qnrs', 'slug', nullable=False)

def downgrade() -> None:
    op.drop_index('ix_qnrs_slug')
    op.drop_column('qnrs', 'slug')
```

**Why nullable first?**
- ✅ Fast: Adding nullable column is instant (no row rewrites)
- ✅ Safe: Backfill can be batched or done separately
- ✅ Reversible: Easy to rollback if issues arise

---

### 2. Split Column into Multiple Columns

**Use case**: Normalize data (e.g., split `name` into `first_name` + `last_name`)

```python
def upgrade() -> None:
    # Add new columns
    op.add_column('users', 
        sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('users', 
        sa.Column('last_name', sa.String(), nullable=True))
    
    # Backfill by splitting existing name
    op.execute("""
        UPDATE users 
        SET 
            first_name = SPLIT_PART(username, ' ', 1),
            last_name = SPLIT_PART(username, ' ', 2)
        WHERE first_name IS NULL
    """)
    
    # Keep original column for now (safe rollback)
    # Drop 'username' in a future migration after verification

def downgrade() -> None:
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
```

**Best practice**: Keep old column during transition period.

---

### 3. Enum/Status Field Migration

**Use case**: Add new status values or restructure status enum

```python
def upgrade() -> None:
    # Add new status column with default
    op.add_column('qnr_sessions', 
        sa.Column('status', sa.String(), 
                  server_default='in_progress', 
                  nullable=False))
    
    # Backfill based on existing fields
    op.execute("""
        UPDATE qnr_sessions 
        SET status = CASE
            WHEN completed_at IS NOT NULL THEN 'completed'
            WHEN started_at IS NULL THEN 'pending'
            ELSE 'in_progress'
        END
    """)
    
    op.create_index('ix_qnr_sessions_status', 
                    'qnr_sessions', ['status'])

def downgrade() -> None:
    op.drop_index('ix_qnr_sessions_status')
    op.drop_column('qnr_sessions', 'status')
```

---

### 4. Foreign Key Data Migration

**Use case**: Establish relationships between existing records

```python
def upgrade() -> None:
    # Add FK column as nullable
    op.add_column('memos', 
        sa.Column('qnr_id', sa.Uuid(), nullable=True))
    
    # Backfill: Link memos to qnrs via session
    op.execute("""
        UPDATE memos m
        SET qnr_id = s.qnr_id
        FROM qnr_sessions s
        WHERE m.session_id = s.id
        AND m.qnr_id IS NULL
    """)
    
    # Add FK constraint
    op.create_foreign_key(
        'fk_memos_qnr_id_qnrs', 
        'memos', 'qnrs', 
        ['qnr_id'], ['id']
    )

def downgrade() -> None:
    op.drop_constraint('fk_memos_qnr_id_qnrs', 'memos')
    op.drop_column('memos', 'qnr_id')
```

---

### 5. Data Cleanup Migration

**Use case**: Remove orphaned or invalid data

```python
def upgrade() -> None:
    # Delete orphaned sessions (user was deleted)
    op.execute("""
        DELETE FROM qnr_sessions 
        WHERE user_id NOT IN (SELECT id FROM users)
    """)
    
    # Delete invalid sessions (no start time but has completion)
    op.execute("""
        DELETE FROM qnr_sessions 
        WHERE started_at IS NULL 
        AND completed_at IS NOT NULL
    """)

def downgrade() -> None:
    # Data cleanup is usually irreversible
    # Can't restore deleted data
    pass
```

**Warning**: Data cleanup is usually **irreversible**. Test thoroughly on staging!

---

## Safe Practices

### 1. Always Use Nullable First for Large Tables

```python
# ❌ DANGEROUS on large tables (causes full table rewrite)
op.add_column('users', 
    sa.Column('phone', sa.String(), 
              server_default='', 
              nullable=False))

# ✅ SAFE (instant metadata change)
op.add_column('users', 
    sa.Column('phone', sa.String(), 
              nullable=True))
```

**Why?**
- Adding `NOT NULL` with `server_default` requires PostgreSQL to rewrite entire table
- For tables with millions of rows, this can take minutes and lock the table
- Adding nullable column is instant (just metadata)

---

### 2. Batch Large Updates

```python
def upgrade() -> None:
    # Add column
    op.add_column('qnrs', 
        sa.Column('slug', sa.String(), nullable=True))
    
    # ❌ BAD: Update all rows at once (locks table)
    # op.execute("UPDATE qnrs SET slug = ...")
    
    # ✅ GOOD: Batch updates
    connection = op.get_bind()
    
    batch_size = 1000
    offset = 0
    
    while True:
        result = connection.execute(sa.text("""
            UPDATE qnrs 
            SET slug = LOWER(REGEXP_REPLACE(title, '[^a-zA-Z0-9]+', '-', 'g'))
            WHERE slug IS NULL
            AND id IN (
                SELECT id FROM qnrs 
                WHERE slug IS NULL 
                LIMIT :batch_size OFFSET :offset
            )
        """), {"batch_size": batch_size, "offset": offset})
        
        if result.rowcount == 0:
            break
        
        offset += batch_size
```

**Benefits**:
- Smaller transaction locks
- Can be interrupted and resumed
- Progress visibility

---

### 3. Test on Staging with Production-Like Data

```bash
# 1. Create migration locally
uv run alembic revision -m "Backfill user slugs"

# 2. Add data migration code
# Edit alembic/versions/XXXX_backfill_user_slugs.py

# 3. Test locally with small dataset
uv run alembic upgrade head

# 4. Deploy to staging (auto-deploy)
git add alembic/versions/
git commit -m "migration: Backfill user slugs"
git push origin dev

# 5. Verify on staging
# → Check Render logs for migration time
# → Verify data correctness in Neon dev branch
# → Test application behavior

# 6. If good, deploy to production
git checkout main
git merge dev
git tag v0.2.0
git push --tags
```

---

### 4. Make Data Migrations Idempotent

```python
# ✅ GOOD: Idempotent (safe to run multiple times)
def upgrade() -> None:
    op.execute("""
        UPDATE users 
        SET full_name = username 
        WHERE full_name IS NULL  -- ← Only update missing values
    """)

# ❌ BAD: Not idempotent (overwrites on every run)
def upgrade() -> None:
    op.execute("""
        UPDATE users 
        SET full_name = username
    """)
```

**Why idempotent?**
- Safe if migration needs to be re-run
- Won't corrupt data if accidentally applied twice
- Allows partial completion and resume

---

### 5. Log Migration Progress

```python
def upgrade() -> None:
    connection = op.get_bind()
    
    # Count before
    result = connection.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE full_name IS NULL"
    ))
    before_count = result.scalar()
    print(f"📊 Rows to migrate: {before_count}")
    
    # Perform migration
    op.execute("""
        UPDATE users 
        SET full_name = username 
        WHERE full_name IS NULL
    """)
    
    # Count after
    result = connection.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE full_name IS NULL"
    ))
    after_count = result.scalar()
    print(f"✅ Rows remaining: {after_count}")
    print(f"✅ Migrated: {before_count - after_count} rows")
```

**Benefits**:
- Visibility into migration progress
- Helps debug issues
- Confirms migration success

---

## Zero-Downtime Strategies

### Pattern: Add Column → Backfill → Make Required

**Problem**: Adding NOT NULL column causes downtime (table rewrite)

**Solution**: Multi-phase migration

#### Phase 1: Add Nullable Column

```python
# Migration: 001_add_phone_column.py
def upgrade() -> None:
    op.add_column('users', 
        sa.Column('phone', sa.String(), nullable=True))
    
    # Deploy code that writes to phone (but doesn't require it yet)
```

#### Phase 2: Backfill Data (Optional Background Job)

```python
# Option A: In migration
# Migration: 002_backfill_phone.py
def upgrade() -> None:
    op.execute("""
        UPDATE users 
        SET phone = '' 
        WHERE phone IS NULL
    """)

# Option B: Background job (better for huge tables)
# Don't block deployment, backfill async
```

#### Phase 3: Make Column Required

```python
# Migration: 003_phone_not_null.py
def upgrade() -> None:
    # Ensure all nulls are gone
    op.execute("""
        UPDATE users 
        SET phone = '' 
        WHERE phone IS NULL
    """)
    
    # Now safe to make NOT NULL
    op.alter_column('users', 'phone', nullable=False)
    
    # Deploy code that requires phone
```

**Timeline**: 3 separate deployments, zero downtime

---

### Pattern: Rename Column (Zero Downtime)

**Problem**: Renaming column breaks old code that's still running

**Solution**: Add new column → Dual write → Migrate → Remove old

#### Phase 1: Add New Column

```python
# Migration: 001_add_username.py
def upgrade() -> None:
    op.add_column('users', 
        sa.Column('username', sa.String(), nullable=True))
    
    # Backfill from old column
    op.execute("UPDATE users SET username = user_name")

# Deploy code that writes to BOTH user_name and username
```

#### Phase 2: Make New Column Primary

```python
# Migration: 002_make_username_required.py
def upgrade() -> None:
    op.alter_column('users', 'username', nullable=False)

# Deploy code that only uses username (ignores user_name)
```

#### Phase 3: Drop Old Column

```python
# Migration: 003_drop_user_name.py
def upgrade() -> None:
    op.drop_column('users', 'user_name')
```

**Timeline**: 3 deployments, old and new code coexist gracefully

---

## Testing Data Migrations

### Local Testing

```bash
# 1. Create test database with data
# Use Neon dev branch or local PostgreSQL

# 2. Add test data
psql $DATABASE_URL -c "
    INSERT INTO users (id, email, username) 
    VALUES 
        (gen_random_uuid(), 'test1@example.com', 'user1'),
        (gen_random_uuid(), 'test2@example.com', 'user2');
"

# 3. Run migration
uv run alembic upgrade head

# 4. Verify data
psql $DATABASE_URL -c "
    SELECT id, email, username, full_name 
    FROM users;
"

# 5. Test downgrade
uv run alembic downgrade -1

# 6. Verify data restored
psql $DATABASE_URL -c "
    SELECT id, email, username 
    FROM users;
"
```

---

### Staging Testing

```bash
# 1. Push to dev branch
git push origin dev

# 2. Monitor deployment logs
# Look for:
# - Migration completion time
# - Number of rows affected
# - Any errors or warnings

# 3. Verify in your PostgreSQL console
# Run SQL queries to check data correctness

# 4. Test application behavior
# → Visit https://core-staging.example.com
# → Test affected features
# → Check API responses
```

---

### Migration Performance Testing

```python
# Add timing to migration
import time

def upgrade() -> None:
    print("🚀 Starting data migration...")
    start = time.time()
    
    op.execute("""
        UPDATE users 
        SET full_name = username 
        WHERE full_name IS NULL
    """)
    
    elapsed = time.time() - start
    print(f"✅ Migration completed in {elapsed:.2f} seconds")
```

**Watch for**:
- Migrations taking >30 seconds (may need batching)
- Table locks causing timeouts
- Memory issues on large updates

---

## Examples

### Example 1: Add Computed Field

**Scenario**: Add `is_complete` boolean based on `completed_at`

```python
"""Add is_complete flag to sessions

Revision ID: abc123def456
Revises: prev_revision_id
Create Date: 2025-01-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'abc123def456'
down_revision = 'prev_revision_id'

def upgrade() -> None:
    # Add column with default
    op.add_column('qnr_sessions',
        sa.Column('is_complete', sa.Boolean(),
                  server_default=sa.false(),
                  nullable=False))
    
    # Backfill based on completed_at
    op.execute("""
        UPDATE qnr_sessions
        SET is_complete = (completed_at IS NOT NULL)
    """)
    
    # Add index for querying
    op.create_index('ix_qnr_sessions_is_complete',
                    'qnr_sessions', ['is_complete'])
    
    print("✅ Backfilled is_complete for all sessions")

def downgrade() -> None:
    op.drop_index('ix_qnr_sessions_is_complete')
    op.drop_column('qnr_sessions', 'is_complete')
```

---

### Example 2: Data Normalization

**Scenario**: Extract tags from `graph_data` JSONB into separate table

```python
"""Extract tags from QNR graph_data to separate table

Revision ID: def456ghi789
Revises: abc123def456
Create Date: 2025-01-20 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'def456ghi789'
down_revision = 'abc123def456'

def upgrade() -> None:
    # Create tags table
    op.create_table('qnr_tags',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qnr_id', sa.Uuid(), nullable=False),
        sa.Column('tag', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['qnr_id'], ['qnrs.id'],
                                name='fk_qnr_tags_qnr_id_qnrs'),
        sa.PrimaryKeyConstraint('id', name='pk_qnr_tags')
    )
    op.create_index('ix_qnr_tags_qnr_id', 'qnr_tags', ['qnr_id'])
    op.create_index('ix_qnr_tags_tag', 'qnr_tags', ['tag'])
    
    # Extract tags from graph_data
    op.execute("""
        INSERT INTO qnr_tags (id, qnr_id, tag)
        SELECT 
            gen_random_uuid(),
            id,
            jsonb_array_elements_text(graph_data->'tags')
        FROM qnrs
        WHERE graph_data ? 'tags'
    """)
    
    connection = op.get_bind()
    result = connection.execute(sa.text(
        "SELECT COUNT(*) FROM qnr_tags"
    ))
    count = result.scalar()
    print(f"✅ Extracted {count} tags from {result.rowcount} QNRs")

def downgrade() -> None:
    op.drop_index('ix_qnr_tags_tag')
    op.drop_index('ix_qnr_tags_qnr_id')
    op.drop_table('qnr_tags')
```

---

### Example 3: Clean Up Invalid Data

**Scenario**: Remove orphaned sessions and fix timestamps

```python
"""Clean up orphaned sessions and invalid timestamps

Revision ID: ghi789jkl012
Revises: def456ghi789
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'ghi789jkl012'
down_revision = 'def456ghi789'

def upgrade() -> None:
    connection = op.get_bind()
    
    # Count orphaned sessions
    result = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM qnr_sessions 
        WHERE user_id NOT IN (SELECT id FROM users)
    """))
    orphaned_count = result.scalar()
    print(f"📊 Found {orphaned_count} orphaned sessions")
    
    # Delete orphaned sessions
    op.execute("""
        DELETE FROM qnr_sessions 
        WHERE user_id NOT IN (SELECT id FROM users)
    """)
    
    # Fix invalid timestamps (completed before started)
    result = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM qnr_sessions 
        WHERE completed_at < started_at
    """))
    invalid_count = result.scalar()
    print(f"📊 Found {invalid_count} invalid timestamps")
    
    op.execute("""
        UPDATE qnr_sessions 
        SET completed_at = NULL 
        WHERE completed_at < started_at
    """)
    
    print(f"✅ Cleaned up {orphaned_count} orphaned sessions")
    print(f"✅ Fixed {invalid_count} invalid timestamps")

def downgrade() -> None:
    # Data cleanup is irreversible
    print("⚠️ Cannot restore deleted data")
    pass
```

---

## Troubleshooting

### Issue: Migration Timeout

**Symptom**: Migration fails with timeout error

**Cause**: Large data update taking too long

**Fix**: Batch the update

```python
# Instead of:
op.execute("UPDATE users SET full_name = username")

# Do:
connection = op.get_bind()
batch_size = 1000
offset = 0

while True:
    result = connection.execute(sa.text("""
        WITH batch AS (
            SELECT id FROM users 
            WHERE full_name IS NULL 
            LIMIT :batch_size
        )
        UPDATE users 
        SET full_name = username 
        WHERE id IN (SELECT id FROM batch)
    """), {"batch_size": batch_size})
    
    if result.rowcount == 0:
        break
```

---

### Issue: Deadlock During Migration

**Symptom**: `deadlock detected` error

**Cause**: Multiple processes updating same rows in different order

**Fix**: Use explicit row locking order

```python
# Lock rows in consistent order (by ID)
op.execute("""
    UPDATE users 
    SET full_name = username 
    WHERE id IN (
        SELECT id FROM users 
        WHERE full_name IS NULL 
        ORDER BY id  -- ← Consistent locking order
        FOR UPDATE SKIP LOCKED  -- ← Skip if locked
    )
""")
```

---

### Issue: Out of Memory

**Symptom**: Migration crashes with OOM error

**Cause**: Loading too many rows into memory

**Fix**: Use server-side cursor or smaller batches

```python
# Use SQL-only updates (no Python memory)
op.execute("""
    UPDATE users 
    SET full_name = username 
    WHERE full_name IS NULL
""")

# Or batch smaller
batch_size = 100  # Smaller batches
```

---

### Issue: Data Corruption After Migration

**Symptom**: Invalid data in migrated rows

**Cause**: Logic error in UPDATE statement

**Fix**: 
1. Test on staging first (always!)
2. Add validation query after migration
3. Have rollback plan

```python
def upgrade() -> None:
    # Perform migration
    op.execute("""
        UPDATE users 
        SET full_name = username 
        WHERE full_name IS NULL
    """)
    
    # Validate results
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM users 
        WHERE full_name IS NULL 
        OR full_name = ''
    """))
    invalid_count = result.scalar()
    
    if invalid_count > 0:
        raise Exception(
            f"❌ Migration validation failed: {invalid_count} "
            f"users still have invalid full_name"
        )
    
    print("✅ Migration validated successfully")
```

---

## Best Practices Checklist

Before committing a data migration:

- [ ] Migration is idempotent (safe to run multiple times)
- [ ] Large updates are batched (< 1000 rows per batch)
- [ ] Progress logging included
- [ ] Validation query included
- [ ] Tested locally with realistic data
- [ ] Tested on staging environment
- [ ] Downgrade() function implemented (if possible)
- [ ] Reviewed by teammate (for production)
- [ ] Timing estimates documented
- [ ] Rollback plan documented

---

## Additional Resources

- [Alembic Documentation - Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
- [PostgreSQL ALTER TABLE Performance](https://www.postgresql.org/docs/current/sql-altertable.html)
- [Zero-Downtime Postgres Migrations](https://github.com/ankane/strong_migrations)
- Alembic env advisory locks — see `alembic/env.py`
- Schema migration patterns — prefer two-phase nullable → backfill → tighten

---

## Summary

**Key Principles**:
1. **Separate schema from data** - Add nullable first, backfill later
2. **Test on staging** - Always verify with production-like data
3. **Make migrations idempotent** - Safe to run multiple times
4. **Batch large updates** - Prevent timeouts and locks
5. **Log progress** - Visibility into migration execution
6. **Validate results** - Ensure data correctness
7. **Plan for rollback** - Know how to undo changes

**Your staging environment is perfect for testing data migrations!** Use it. 🎯


