# QNR Public/Private Versioning Implementation Plan

**Status**: ✅ IMPLEMENTED (December 2025)  
**Created**: 2025-11-12  
**Updated**: 2025-12-07 (Implementation completed)
**Replaces**: QNR_VERSIONING_PLAN.md (updated approach)  
**Related Docs**: [DATA_SCHEMA.md](./DATA_SCHEMA.md), [LANGGRAPH_INTEGRATION_GUIDE.md](./LANGGRAPH_INTEGRATION_GUIDE.md)

---

## Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Database Schema Changes](#database-schema-changes)
4. [Business Logic & Rules](#business-logic--rules)
5. [User Experience Flows](#user-experience-flows)
6. [Implementation Phases](#implementation-phases)
7. [Code Examples](#code-examples)
8. [Testing Checklist](#testing-checklist)
9. [Lessons Learned Applied](#lessons-learned-applied)

---

## Overview

### The Problem

The current `status` field (`"draft"`, `"published"`, `"archived"`) creates confusion:
- Publishing feels permanent (one-way action)
- No easy way to "unpublish" without archiving
- Versioning + status creates complexity: "Can I publish v2 while v1 is published?"
- "Archived" meaning is unclear (hidden from author too?)

### The Solution

**Replace status with simple visibility toggle:**
- `is_public: bool` - Controls public visibility (default `False`)
- `is_current: bool` - Marks latest version in a family (default `True`)
- **Only one version can be public at once** (auto-enforced)
- Authors can toggle public ↔ private anytime
- Users retain access to sessions regardless of visibility changes

### Why This Works

✅ **Simpler mental model**: "Private" (only I see) vs "Public" (everyone sees)  
✅ **Flexible**: Toggle visibility anytime, not permanent  
✅ **Version clarity**: "Only one public version" auto-solves conflicts  
✅ **User-friendly**: Users keep their session access even if QNR goes private  
✅ **No deletion**: Everything is preserved, just hidden  

---

## Design Philosophy

### Core Principles

1. **Visibility is Not Status**: Separate "workflow state" from "public access"
2. **User Data is Sacred**: Sessions survive visibility changes forever
3. **Transparency**: Users know when a newer version is available
4. **Author Control**: Authors decide what the public sees
5. **No Data Loss**: All versions remain accessible for review

### Key User Scenarios

| Scenario | Behavior |
|----------|----------|
| **Author creates QNR** | Defaults to private; only author sees it |
| **Author sets v1 to public** | Appears in "Publicly Available" list |
| **Author creates v2 from v1** | v2 is private (draft), v1 stays public |
| **Author sets v2 to public** | v2 becomes public, v1 auto-set to private, users with v1 sessions see "New version available" |
| **User has active v1 session** | Can continue v1 OR start fresh v2 |
| **User completed v1 session** | Can review v1 OR retake with v2 |
| **Author sets v2 to private** | v2 disappears from public list, no new sessions allowed |

---

## Database Schema Changes

### Migration: Remove Status, Add Visibility

```sql
-- Migration: YYYYMMDD_HHMM_public_private_visibility.py

-- Drop old status column
ALTER TABLE qnrs DROP COLUMN IF EXISTS status;

-- Add new is_public column
ALTER TABLE qnrs ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT FALSE;

-- Create index for fast "public QNRs" queries
CREATE INDEX idx_qnr_is_public ON qnrs(is_public) WHERE is_public = TRUE;

-- Versioning fields already exist from previous migration:
-- version_number INTEGER NOT NULL DEFAULT 1
-- parent_qnr_id UUID REFERENCES qnrs(id) ON DELETE SET NULL
-- is_current BOOLEAN NOT NULL DEFAULT TRUE

COMMENT ON COLUMN qnrs.is_public IS 'Controls public visibility (false = private, true = public)';
```

### Updated QNR Model

**File**: `smeme/core/models.py`

```python
from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy.orm import Mapped
from typing import Optional
from uuid import UUID

class QNR(SQLModel, table=True):
    __tablename__ = "qnrs"
    
    # ... existing fields (id, title, description, author_id, graph_data, etc.) ...
    
    # ============================================================================
    # Visibility & Versioning
    # ============================================================================
    
    is_public: bool = Field(
        default=False,
        sa_column_kwargs={"nullable": False, "index": True},
        description="Controls public visibility (private by default)",
    )
    
    version_number: int = Field(
        default=1,
        ge=1,
        sa_column_kwargs={"nullable": False},
        description="Incremental version number (v1, v2, v3, etc.)",
    )
    
    parent_qnr_id: UUID | None = Field(
        default=None,
        foreign_key="qnrs.id",
        sa_column_kwargs={"nullable": True, "ondelete": "SET NULL"},
        description="Parent version QNR ID (NULL for root versions)",
    )
    
    is_current: bool = Field(
        default=True,
        sa_column_kwargs={"nullable": False, "index": True},
        description="Is this the current/latest version in its family?",
    )
    
    # ============================================================================
    # Relationships (lazy="raise" by default to prevent accidental loads)
    # ============================================================================
    
    # Version chain relationships (small, frequently accessed - use selectin)
    parent: Optional["QNR"] = Relationship(
        sa_relationship_kwargs={
            "remote_side": "QNR.id",
            "foreign_keys": "QNR.parent_qnr_id",
            "lazy": "selectin",  # Small relationship, frequently needed
        }
    )
    
    children: list["QNR"] = Relationship(
        sa_relationship_kwargs={
            "remote_side": "QNR.id",
            "foreign_keys": "QNR.parent_qnr_id",
            "lazy": "selectin",  # Small relationship, frequently needed
        }
    )
    
    # Session relationship (potentially large - use raise to prevent accidents)
    sessions: list["QNRSession"] = Relationship(
        back_populates="qnr",
        sa_relationship_kwargs={
            "lazy": "raise",  # Prevents accidental loads and timestamp updates
        },
    )
    
    # ============================================================================
    # Helper Methods
    # ============================================================================
    
    def get_root_version(self) -> "QNR":
        """Get the root (v1) version in this QNR's family."""
        root = self
        while root.parent_qnr_id and root.parent:
            root = root.parent
        return root
    
    def get_version_family(self) -> list["QNR"]:
        """
        Get all versions in this QNR's family (root + descendants).
        Returns list ordered by version_number.
        """
        root = self.get_root_version()
        family = [root] + root._get_all_descendants()
        return sorted(family, key=lambda q: q.version_number)
    
    def _get_all_descendants(self) -> list["QNR"]:
        """Recursively get all child versions."""
        descendants = []
        for child in self.children:
            descendants.append(child)
            descendants.extend(child._get_all_descendants())
        return descendants
    
    @property
    def display_badge(self) -> str:
        """Badge text for UI display."""
        if self.is_public:
            return "🌐 Public"
        return "🔒 Private"
```

---

## Business Logic & Rules

### Rule 1: Only One Version Public at a Time

When an author sets a version to public, **all other versions in the family** are automatically set to private.

```python
async def set_qnr_public(db: AsyncSession, qnr: QNR) -> None:
    """
    Make this QNR version public.
    Auto-sets all siblings and parent to private.
    """
    # Get all versions in the family
    family = qnr.get_version_family()
    
    # Set all to private except this one
    for version in family:
        if version.id == qnr.id:
            version.is_public = True
        else:
            version.is_public = False
        db.add(version)
    
    await db.commit()
```

### Rule 2: Session Access Preservation

Users who started a session when a QNR was public retain access even if it goes private later.

```python
async def can_access_qnr(
    db: AsyncSession,
    qnr_id: UUID,
    user_id: UUID,
) -> bool:
    """
    Check if user can access QNR.
    
    Returns True if:
    1. User owns the QNR (author), OR
    2. QNR is public, OR
    3. User has an existing session with this QNR
    """
    qnr = await db.get(QNR, qnr_id)
    if not qnr:
        return False
    
    # Author can always access
    if qnr.author_id == user_id:
        return True
    
    # Public QNRs are accessible
    if qnr.is_public:
        return True
    
    # Check for existing session (preserves access)
    result = await db.execute(
        select(QNRSession)
        .where(
            QNRSession.qnr_id == qnr_id,
            QNRSession.user_id == user_id,
        )
    )
    existing_session = result.scalar_one_or_none()
    
    return existing_session is not None
```

### Rule 3: New Sessions Require Public Status

Users can only **start new sessions** on public QNRs (unless they're the author).

```python
@router.post("/{qnr_id}/start")
async def start_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Start a new QNR session."""
    qnr = await db.get(QNR, qnr_id)
    
    # Authors can always start sessions
    if qnr.author_id != user.id:
        # Non-authors need QNR to be public
        if not qnr.is_public:
            raise HTTPException(
                status_code=403,
                detail="This QNR is no longer publicly available"
            )
    
    # Create session...
```

### Rule 4: Default Visibility

All new and generated QNRs default to **private**.

```python
# When creating a new QNR
new_qnr = QNR(
    title="My QNR",
    author_id=user.id,
    is_public=False,  # ← Default
    version_number=1,
    is_current=True,
)

# When generating a QNR
generated_qnr = QNR(
    title=generated_title,
    author_id=user.id,
    is_public=False,  # ← Default
    graph_data=generated_graph,
)
```

### Rule 5: Public QNRs Are Read-Only in Editor

Public QNRs **cannot be edited directly** in the editor interface. Any attempt to edit automatically creates a new private version.

```python
async def enforce_versioning_for_public_edits(
    db: AsyncSession,
    qnr: QNR,
    user_id: UUID,
) -> QNR:
    """
    Enforce versioning for public QNR edits.

    If the QNR is public, automatically creates a new private version
    and returns that for editing instead. If the QNR is private,
    returns the original QNR for direct editing.
    """
    # If QNR is private, allow direct editing
    if not qnr.is_public:
        return qnr

    # QNR is public - force creation of new private version
    # ... create new version logic ...
    return new_version
```

**UI Behavior:**
- Public QNRs show read-only interface with clear messaging
- "Create New Version" button is prominently displayed
- Backend enforcement ensures no direct edits even if UI is bypassed

---

## User Experience Flows

### Flow 1: Author Creates and Publishes QNR

```
[Generate/Create QNR]
    ↓
[QNR is Private (only author sees it)]
    ↓
[Author edits and refines]
    ↓
[Author clicks "Set Public" → Confirmation popup]
    ↓
[QNR becomes Public → Appears in "Publicly Available"]
    ↓
[Users can start new sessions]
```

### Flow 2: Author Creates New Version

```
[Viewing v1 (Public)]
    ↓
[Click "Create New Version" → Confirmation popup]
    ↓
[v2 created as Private, v1 stays Public]
    ↓
[Author edits v2 privately]
    ↓
[Author clicks "Set Public" on v2 → Confirmation popup]
    ↓
[v2 becomes Public, v1 auto-set to Private]
    ↓
[Users with v1 sessions see "⬆️ v2 Available" badge]
```

### Flow 3: User Encounters Outdated QNR

```
[User visits Dashboard]
    ↓
[Amber banner: "New version available for Assessment X"]
    ↓
[User clicks session in Recent Sessions table]
    ↓
[Session row shows "⬆️ v2 Available" badge]
    ↓
[User clicks badge → Version info modal]
    ↓
[Modal shows: v1 (your progress) vs v2 (new version)]
    ↓
Option A: [Continue v1] → Resume where left off
Option B: [Start v2] → New session with updated questions
```

### Flow 4: Author Hides QNR from Public

```
[Viewing v2 (Public)]
    ↓
[Click "Set Private" → Confirmation popup]
    ↓
[v2 becomes Private → Disappears from public list]
    ↓
[Existing user sessions preserved]
    ↓
[New users see "This QNR is no longer available" if they try to access]
```

### Flow 5: Author Attempts Direct Edit of Public QNR

```
[Viewing v2 (Public) in Editor]
    ↓
[UI shows warning banner + non-interactive graph]
    ↓
[Author clicks "Create New Version" → Confirmation popup]
    ↓
[System creates v3 as Private]
    ↓
[Browser redirects to v3 editor page]
    ↓
[Author can now edit v3 privately]
    ↓
[Original v2 remains Public and unchanged]
```

**Key Points:**
- **Complete UI blocking**: Public QNRs show warning banner AND disable graph interaction
- **Non-interactive graph**: Nodes show "not-allowed" cursor and alert on click
- **Explicit user action required**: Must click "Create New Version" button
- **No accidental edits**: Impossible to edit public QNRs through UI
- **Backend safety net**: If somehow bypassed, system creates new version anyway

---

## Implementation Phases

### Phase 1: Database Migration ✨

**Estimated Time**: 30 minutes

1. **Create migration file**
   ```bash
   uv run alembic revision -m "remove_status_add_is_public"
   ```

2. **Write migration**
   ```python
   # alembic/versions/YYYYMMDD_HHMM_remove_status_add_is_public.py
   
   def upgrade():
       # Drop old status column (destructive - user said OK)
       op.drop_column('qnrs', 'status')
       
       # Add is_public column
       op.add_column('qnrs', sa.Column('is_public', sa.Boolean(), 
                                        nullable=False, server_default='false'))
       
       # Create index for fast public QNR queries
       op.create_index('idx_qnr_is_public', 'qnrs', ['is_public'], 
                       postgresql_where=sa.text('is_public = true'))
   
   def downgrade():
       op.drop_index('idx_qnr_is_public', table_name='qnrs')
       op.drop_column('qnrs', 'is_public')
       # Optionally restore status column (but user said no need)
   ```

3. **Run migration**
   ```bash
   uv run alembic upgrade head
   ```

4. **Update model** (`smeme/core/models.py`)
   - Remove `status` field
   - Add `is_public` field
   - Update relationships (already done in previous migration)

### Phase 2: Backend Routes & Logic 🔧

**Estimated Time**: 2 hours

1. **Add public/private toggle routes**

```python
# smeme/qnr/editor/routes.py

@router.post("/{qnr_id}/set_public")
async def set_qnr_public(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> RedirectResponse:
    """
    Make this version public.
    Auto-sets all other versions (siblings + parent) to private.
    """
    # Load QNR with version relationships
    result = await db.execute(
        select(QNR)
        .options(
            selectinload(QNR.parent),
            selectinload(QNR.children),
        )
        .where(QNR.id == qnr_id, QNR.author_id == user.id)
    )
    qnr = result.scalar_one_or_none()
    
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    # Get all versions in family
    family = qnr.get_version_family()
    
    # Set all to private except this one
    for version in family:
        if version.id == qnr.id:
            version.is_public = True
            logger.info(
                f"Setting QNR to public: {version.title}",
                extra={
                    "qnr_id": str(version.id),
                    "version_number": version.version_number,
                    "user_id": str(user.id),
                },
            )
        else:
            version.is_public = False
            logger.info(
                f"Auto-setting sibling to private: {version.title}",
                extra={
                    "qnr_id": str(version.id),
                    "version_number": version.version_number,
                    "reason": "sibling_made_public",
                },
            )
        db.add(version)
    
    await db.commit()
    
    # Redirect to dashboard
    response = RedirectResponse(url="/qnr/dashboard", status_code=303)
    return response


@router.post("/{qnr_id}/set_private")
async def set_qnr_private(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> RedirectResponse:
    """
    Make this version private.
    It will be hidden from public view but remain accessible to author
    and users with existing sessions.
    """
    qnr = await db.get(QNR, qnr_id)
    
    if not qnr or qnr.author_id != user.id:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    qnr.is_public = False
    db.add(qnr)
    await db.commit()
    
    logger.info(
        f"Setting QNR to private: {qnr.title}",
        extra={
            "qnr_id": str(qnr.id),
            "version_number": qnr.version_number,
            "user_id": str(user.id),
        },
    )
    
    # Redirect to dashboard
    response = RedirectResponse(url="/qnr/dashboard", status_code=303)
    return response
```

2. **Update dashboard queries**

```python
# smeme/qnr/routes.py

@router.get("/dashboard", response_class=HTMLResponse)
async def qnr_dashboard(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    templates: Jinja2TemplatesDep,
):
    """Dashboard showing QNRs with public/private visibility."""
    
    # Self Authored: All versions, any visibility
    my_qnrs_query = (
        select(QNR)
        .where(QNR.author_id == user.id)
        .order_by(QNR.updated_at.desc())
    )
    result = await db.execute(my_qnrs_query)
    my_qnrs = list(result.scalars().all())
    
    # Publicly Available: Only public + current versions from others
    available_qnrs_query = (
        select(QNR)
        .where(
            QNR.is_public == True,        # Only public
            QNR.is_current == True,        # Only current versions
            QNR.author_id != user.id,      # Not authored by user
        )
        .order_by(QNR.updated_at.desc())
    )
    result = await db.execute(available_qnrs_query)
    available_qnrs = list(result.scalars().all())
    
    # Get recent sessions with QNR eager loaded
    sessions_query = (
        select(QNRSession)
        .options(
            selectinload(QNRSession.qnr).selectinload(QNR.parent),
            selectinload(QNRSession.qnr).selectinload(QNR.children),
        )
        .where(QNRSession.user_id == user.id)
        .order_by(QNRSession.updated_at.desc())
        .limit(20)
    )
    result = await db.execute(sessions_query)
    sessions = list(result.scalars().all())
    
    # Check for sessions with newer public versions available
    sessions_with_updates = []
    for session in sessions:
        newer_version = await get_newer_public_version(db, session.qnr)
        sessions_with_updates.append({
            "session": session,
            "newer_version": newer_version,
        })
    
    return templates.TemplateResponse(
        "qnr/dashboard.html",
        {
            "request": request,
            "user": user,
            "my_qnrs": my_qnrs,
            "available_qnrs": available_qnrs,
            "sessions_with_updates": sessions_with_updates,
        },
    )
```

3. **Add helper: Check for newer public versions**

```python
# smeme/qnr/helpers/db_queries.py

async def get_newer_public_version(
    db: AsyncSession,
    current_qnr: QNR,
) -> QNR | None:
    """
    Get newer public version if one exists.
    
    Returns the newest public version in the family that's newer than current,
    or None if no newer public version exists.
    """
    # Get all versions in family
    family = current_qnr.get_version_family()
    
    # Filter to public versions newer than current
    newer_public = [
        v for v in family
        if v.is_public and v.version_number > current_qnr.version_number
    ]
    
    if not newer_public:
        return None
    
    # Return the newest one
    return max(newer_public, key=lambda v: v.version_number)
```

### Phase 3: UI Updates 🎨

**Estimated Time**: 2 hours

1. **Update editor page** (`_editor_content.html`)

```html
<!-- Version and visibility badges -->
<div class="header-badges">
    <!-- Version badge (purple) -->
    <span class="badge badge-purple">v{{ version_number }}</span>
    
    <!-- Visibility badge -->
    {% if is_public %}
        <span class="badge badge-public">🌐 Public</span>
    {% else %}
        <span class="badge badge-private">🔒 Private</span>
    {% endif %}
</div>

<!-- Toggle buttons (regular forms for full page redirect) -->
<div class="visibility-controls">
    {% if is_public %}
        <form method="post" action="/qnr/editor/{{ qnr_id }}/set_private" style="display: inline;">
            <button
                type="submit"
                onclick="return confirm('Set to private? It will be hidden from public view but users with existing sessions will retain access.');"
                class="btn btn-secondary">
                🔒 Set Private
            </button>
        </form>
    {% else %}
        <form method="post" action="/qnr/editor/{{ qnr_id }}/set_public" style="display: inline;">
            <button
                type="submit"
                onclick="return confirm('Set to public? This will hide all other versions from public view.');"
                class="btn btn-primary">
                🌐 Set Public
            </button>
        </form>
    {% endif %}
    
    <!-- Create new version (only if current is public) -->
    {% if is_public %}
        <form method="post" action="/qnr/editor/{{ qnr_id }}/create_version" style="display: inline;">
            <button
                type="submit"
                onclick="return confirm('Create a new version? This will create a private draft copy (v{{ version_number + 1 }}) that you can edit.');"
                class="btn btn-gradient">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                </svg>
                Create New Version
            </button>
        </form>
    {% endif %}
</div>
```

2. **Update dashboard** (`dashboard.html`)

```html
<!-- Self Authored QNRs Section -->
<section class="my-qnrs">
    <h2>Self Authored</h2>
    <table>
        <thead>
            <tr>
                <th>Title</th>
                <th>Version</th>
                <th>Visibility</th>
                <th>Updated</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for qnr in my_qnrs %}
            <tr>
                <td>{{ qnr.title }}</td>
                <td><span class="badge badge-purple">v{{ qnr.version_number }}</span></td>
                <td>
                    {% if qnr.is_public %}
                        <span class="badge badge-public">🌐 Public</span>
                    {% else %}
                        <span class="badge badge-private">🔒 Private</span>
                    {% endif %}
                    {% if not qnr.is_current %}
                        <span class="badge badge-gray">Outdated</span>
                    {% endif %}
                </td>
                <td>{{ qnr.updated_at | timeago }}</td>
                <td>
                    <a href="/qnr/{{ qnr.id }}/editor" class="btn btn-sm">Edit</a>
                    <a href="/qnr/{{ qnr.id }}/start" class="btn btn-sm">Test</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</section>

<!-- Publicly Available QNRs Section -->
<section class="public-qnrs">
    <h2>Publicly Available</h2>
    <div class="qnr-grid">
        {% for qnr in available_qnrs %}
        <div class="qnr-card">
            <h3>{{ qnr.title }}</h3>
            <p>{{ qnr.description }}</p>
            <div class="card-footer">
                <span class="badge badge-purple">v{{ qnr.version_number }}</span>
                <a href="/qnr/{{ qnr.id }}/start" class="btn btn-primary">Start</a>
            </div>
        </div>
        {% endfor %}
    </div>
</section>

<!-- Recent Sessions Section with Update Indicators -->
<section class="recent-sessions">
    <h2>Recent Sessions</h2>
    <table>
        <thead>
            <tr>
                <th>Questionnaire</th>
                <th>Version</th>
                <th>Status</th>
                <th>Last Activity</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for item in sessions_with_updates %}
            <tr>
                <td>{{ item.session.qnr.title }}</td>
                <td>
                    <span class="badge badge-purple">v{{ item.session.qnr.version_number }}</span>
                    {% if item.newer_version %}
                        <span class="badge badge-update" 
                              title="v{{ item.newer_version.version_number }} available">
                            ⬆️ New Version
                        </span>
                    {% endif %}
                </td>
                <td>{{ item.session.status }}</td>
                <td>{{ item.session.updated_at | timeago }}</td>
                <td>
                    {% if item.newer_version %}
                        <button 
                            hx-get="/qnr/session/{{ item.session.id }}/version-info"
                            hx-target="#modal-container"
                            hx-swap="innerHTML"
                            class="btn btn-sm btn-info">
                            View Options
                        </button>
                    {% else %}
                        <a href="/qnr/viewer/{{ item.session.qnr.id }}?session_id={{ item.session.id }}" 
                           class="btn btn-sm">Continue</a>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</section>
```

### Phase 4: Version Info Modal (User Decision Point) 🔔

**Estimated Time**: 1.5 hours

1. **Create version info route**

```python
# smeme/qnr/routes.py

@router.get("/session/{session_id}/version-info", response_class=HTMLResponse)
async def session_version_info(
    session_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    templates: Jinja2TemplatesDep,
):
    """Show version comparison modal when user has outdated session."""
    
    # Load session with QNR and version relationships
    result = await db.execute(
        select(QNRSession)
        .options(
            selectinload(QNRSession.qnr).selectinload(QNR.parent),
            selectinload(QNRSession.qnr).selectinload(QNR.children),
        )
        .where(QNRSession.id == session_id, QNRSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get newer public version
    newer_version = await get_newer_public_version(db, session.qnr)
    
    if not newer_version:
        # No update available, redirect to continue session
        return RedirectResponse(
            url=f"/qnr/viewer/{session.qnr.id}?session_id={session.id}",
            status_code=303
        )
    
    # Calculate progress
    is_in_progress = session.started_at and not session.completed_at
    
    # Count answers if in progress
    answers_count = 0
    if is_in_progress and session.data:
        answers_count = len(session.data.get("answers", {}))
    
    return templates.TemplateResponse(
        "qnr/_version_info_modal.html",
        {
            "request": request,
            "session": session,
            "old_qnr": session.qnr,
            "current_qnr": newer_version,
            "is_in_progress": is_in_progress,
            "answers_count": answers_count,
        },
    )
```

2. **Create modal template**

```html
<!-- smeme/templates/qnr/_version_info_modal.html -->
<div class="modal-overlay" onclick="if(event.target === this) document.getElementById('modal-container').innerHTML = ''">
    <div class="modal-dialog">
        
        <!-- Header -->
        <div class="modal-header">
            <div class="icon-info">ℹ️</div>
            <h3>New Version Available</h3>
        </div>
        
        <!-- Content -->
        <div class="modal-body">
            <p><strong>{{ old_qnr.title }}</strong> has been updated by its author.</p>
            
            <!-- Version Comparison -->
            <div class="version-comparison">
                <div class="version-item">
                    <span class="label">Your version:</span>
                    <span class="badge badge-amber">v{{ old_qnr.version_number }}</span>
                </div>
                <div class="version-item">
                    <span class="label">Current version:</span>
                    <span class="badge badge-green">v{{ current_qnr.version_number }}</span>
                </div>
                {% if is_in_progress %}
                <div class="version-item">
                    <span class="label">Your progress:</span>
                    <span>{{ answers_count }} answer{{ 's' if answers_count != 1 else '' }} saved</span>
                </div>
                {% endif %}
            </div>
            
            <!-- Explanation -->
            <div class="explanation">
                {% if is_in_progress %}
                    <p><strong>Your progress on v{{ old_qnr.version_number }} is saved.</strong></p>
                    <p>You can continue where you left off, or start fresh with the new version.</p>
                {% else %}
                    <p><strong>Your completed v{{ old_qnr.version_number }} assessment and memo are preserved.</strong></p>
                    <p>You can review your original results or retake the assessment with the updated version.</p>
                {% endif %}
            </div>
            
            <!-- Options -->
            <ul class="options-list">
                {% if is_in_progress %}
                    <li>Continue with v{{ old_qnr.version_number }} (keep your answers)</li>
                    <li>Start fresh with v{{ current_qnr.version_number }} (new session)</li>
                {% else %}
                    <li>Review your completed v{{ old_qnr.version_number }} assessment</li>
                    <li>Start a new assessment with v{{ current_qnr.version_number }}</li>
                {% endif %}
            </ul>
        </div>
        
        <!-- Action Buttons -->
        <div class="modal-footer">
            {% if is_in_progress %}
                <a href="/qnr/viewer/{{ old_qnr.id }}?session_id={{ session.id }}"
                   class="btn btn-secondary">
                    Continue v{{ old_qnr.version_number }}
                </a>
                <a href="/qnr/{{ current_qnr.id }}/start"
                   class="btn btn-primary">
                    Start v{{ current_qnr.version_number }}
                </a>
            {% else %}
                <a href="/qnr/session/{{ session.id }}/review"
                   class="btn btn-secondary">
                    Review v{{ old_qnr.version_number }}
                </a>
                <a href="/qnr/{{ current_qnr.id }}/start"
                   class="btn btn-primary">
                    Start v{{ current_qnr.version_number }}
                </a>
            {% endif %}
        </div>
        
        <!-- Close Button -->
        <button 
            onclick="document.getElementById('modal-container').innerHTML = ''"
            class="btn-close">
            Close
        </button>
        
    </div>
</div>
```

### Phase 5: Update All Status References 🧹

**Estimated Time**: 1 hour

1. **Search and replace**
   ```bash
   # Find all status references
   grep -r "\.status" smeme/ --include="*.py"
   grep -r "status ==" smeme/ --include="*.py"
   grep -r 'status":"' smeme/templates/ --include="*.html"
   ```

2. **Key files to update**:
   - `smeme/qnr/generation/routes.py` - Generated QNRs default to `is_public=False`
   - `smeme/qnr/viewer/routes.py` - Access control uses `is_public`
   - All templates - Replace status badges with visibility badges

---

## Code Examples

### Example 1: Create New Version

```python
# smeme/qnr/editor/routes.py

@router.post("/{qnr_id}/create_version")
async def create_new_version(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> RedirectResponse:
    """
    Create a new version of an existing QNR.
    
    - New version defaults to private
    - Copies structure from original
    - Marks original as not current
    """
    # Load original with version relationships
    result = await db.execute(
        select(QNR)
        .options(
            selectinload(QNR.parent),
            selectinload(QNR.children),
        )
        .where(QNR.id == qnr_id, QNR.author_id == user.id)
    )
    original = result.scalar_one_or_none()
    
    if not original:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    # Get root QNR for title generation
    root_qnr = original.get_root_version()
    
    # Strip existing version suffix and add new one
    base_title = re.sub(r'\s+v\d+$', '', root_qnr.title)
    new_version_number = original.version_number + 1
    
    # Create new version (private by default)
    new_version = QNR(
        title=f"{base_title} v{new_version_number}",
        description=original.description,
        author_id=user.id,
        version_number=new_version_number,
        parent_qnr_id=original.id,
        is_current=True,
        is_public=False,  # Private by default
        graph_data=copy.deepcopy(original.graph_data) if original.graph_data else {},
    )
    
    # Mark original as not current
    original.is_current = False
    
    db.add(new_version)
    db.add(original)
    await db.commit()
    await db.refresh(new_version)
    
    logger.info(
        f"Created new version: {new_version.title}",
        extra={
            "original_qnr_id": str(original.id),
            "new_qnr_id": str(new_version.id),
            "version_number": new_version_number,
            "user_id": str(user.id),
        },
    )
    
    # Redirect to dashboard where new private draft is visible
    return RedirectResponse(url="/qnr/dashboard", status_code=303)
```

---

## Testing Checklist

### Unit Tests

- [ ] `get_newer_public_version()` returns correct version
- [ ] `get_newer_public_version()` returns None when no newer public version
- [ ] `can_access_qnr()` allows author always
- [ ] `can_access_qnr()` allows if public
- [ ] `can_access_qnr()` allows if user has session
- [ ] `can_access_qnr()` denies otherwise

### Integration Tests

- [ ] Setting v2 to public auto-sets v1 to private
- [ ] Creating v2 leaves v1 public
- [ ] User with v1 session can still access v1 after it goes private
- [ ] User cannot start new session on private QNR (unless author)
- [ ] Generated QNRs default to private
- [ ] Dashboard shows all authored QNRs (public + private)
- [ ] Dashboard shows only public current versions from others

### UI/UX Tests

- [ ] "Set Public" button appears for private QNRs
- [ ] "Set Private" button appears for public QNRs
- [ ] Confirmation popup shows for both actions
- [ ] Version badge shows correctly (v1, v2, etc.)
- [ ] Visibility badge shows correctly (🌐 Public / 🔒 Private)
- [ ] "⬆️ New Version" badge appears in sessions table
- [ ] Version info modal displays correct comparison
- [ ] "Continue v1" button proceeds to old version
- [ ] "Start v2" button creates new session on new version
- [ ] "Create New Version" only appears for public QNRs

### Edge Cases

- [ ] User starts v1, v2 is made public, user can complete v1
- [ ] User completes v1, v2 is made public, memo still accessible
- [ ] Author toggles public → private → public multiple times
- [ ] Multiple users on different versions work independently
- [ ] Version chain with gaps (v1 → v3, v2 deleted) still works

---

## Lessons Learned Applied

### 1. Regular Forms for Full Page Redirects

✅ **Applied**: Toggle buttons use standard `<form>` elements with `onclick` confirmations, not HTMX buttons.

```html
<form method="post" action="/qnr/editor/{{ qnr_id }}/set_public">
    <button type="submit" onclick="return confirm('...');">Set Public</button>
</form>
```

**Why**: HTMX intercepts redirects and swaps content incorrectly. Regular forms ensure clean full-page navigation.

### 2. Lazy Loading Strategy (`lazy="raise"`)

✅ **Applied**: `QNR.sessions` uses `lazy="raise"` to prevent accidental loading and timestamp updates.

```python
sessions: list["QNRSession"] = Relationship(
    sa_relationship_kwargs={"lazy": "raise"}
)
```

**Why**: Prevents all sessions from updating their `updated_at` timestamp when a QNR is modified.

### 3. Eager Loading for Templates

✅ **Applied**: Dashboard queries use `selectinload()` for all relationships accessed in templates.

```python
select(QNRSession).options(
    selectinload(QNRSession.qnr).selectinload(QNR.parent),
    selectinload(QNRSession.qnr).selectinload(QNR.children),
)
```

**Why**: Prevents `MissingGreenlet` errors in Jinja2 templates (which are synchronous).

### 4. Structured Logging

✅ **Applied**: All operations log with structured `extra` dictionaries.

```python
logger.info(
    f"Setting QNR to public: {qnr.title}",
    extra={
        "qnr_id": str(qnr.id),
        "version_number": qnr.version_number,
        "user_id": str(user.id),
    },
)
```

**Why**: Enables filtering logs by session_id, user_id, or qnr_id in production.

### 5. Type Hints with SQLAlchemy Relationships

✅ **Applied**: Uses `Optional["QNR"]` not `"QNR | None"` in relationship type hints.

```python
parent: Optional["QNR"] = Relationship(...)
```

**Why**: SQLAlchemy's string annotation evaluation doesn't support pipe syntax.

### 6. Timezone-Aware Datetimes

✅ **Applied**: All timestamp fields use `datetime.now(UTC)`.

```python
from datetime import UTC, datetime

started_at: Mapped[datetime] = Field(
    default_factory=lambda: datetime.now(UTC),
    sa_column=Column(DateTime(timezone=True))
)
```

**Why**: Prevents naive datetime issues and ensures consistency across timezones.

---

## Success Criteria

Implementation is complete when:

✅ Authors can toggle QNRs between public and private  
✅ Only one version can be public at a time (auto-enforced)  
✅ Generated QNRs default to private  
✅ Dashboard shows all authored QNRs (public + private)  
✅ Dashboard shows only public current versions from others  
✅ Users see "New Version Available" badges in sessions  
✅ Version info modal displays correct comparison  
✅ Users can continue old versions or start new ones  
✅ All sessions survive visibility changes  
✅ No lazy loading errors in templates  
✅ All tests pass  

---

## Migration Impact

**Data Loss**: ✅ Acceptable
- User approved dropping `status` column
- All existing data starts as private (`is_public=False`)
- Authors must manually set QNRs to public after migration

**Breaking Changes**:
- All routes/templates referencing `status` must be updated
- Frontend badges change from "Draft"/"Published" to "Private"/"Public"

**Rollback Plan**:
- Downgrade migration restores structure
- No data restoration needed (user said OK)

---

## Implementation Status

**✅ COMPLETED** - All phases implemented successfully!

### Completed Phases:
- **Phase 1**: Database Migration ✅
- **Phase 2**: Backend Routes & Logic ✅
- **Phase 3**: UI Updates ✅
- **Phase 4**: Version Info Modal ✅
- **Phase 5**: Status References Cleanup ✅

### Additional Enhancements:
- **Versioning Enforcement**: Public QNRs automatically create new versions when edited ✅
- **UI-Level Edit Blocking**: Public QNRs show read-only views with clear warnings ✅
- **MissingGreenlet Fix**: Database query approach prevents async lazy loading errors ✅

### Key Features Working:
✅ Authors can toggle QNRs between public and private
✅ Only one version can be public at a time (auto-enforced)
✅ Generated QNRs default to private
✅ Dashboard shows all authored QNRs (public + private)
✅ Dashboard shows only public current versions from others
✅ Users see "New Version Available" badges in sessions
✅ Version info modal displays correct comparison
✅ Users can continue old versions or start new ones
✅ All sessions survive visibility changes
✅ No lazy loading errors in templates
✅ All tests pass

