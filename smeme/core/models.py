"""Core data models - User, DecisionTree, and DecisionTreeSession only."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi_users_db_sqlmodel import SQLModelBaseUserDB
from sqlalchemy import Column, DateTime, ForeignKey, Index, MetaData, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from smeme.decision_tree.models import InProgressDecisionTreeGeneration

# SQLAlchemy naming conventions for predictable constraint names
# This ensures Alembic can reliably generate migrations over time
# See: https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",  # Index
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # Unique constraint (FIXED typo)
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # Check constraint
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # Foreign key
    "pk": "pk_%(table_name)s",  # Primary key
}

# Create metadata with naming conventions
metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Base model with explicit metadata (ensures naming conventions apply)
class BaseSQLModel(SQLModel):
    """Base model with naming conventions applied.

    All models should inherit from this to ensure consistent constraint naming.
    This prevents SQLAlchemy from using backend-generated names.
    """

    __abstract__ = True  # Not a table itself
    metadata = metadata


class User(BaseSQLModel, SQLModelBaseUserDB, table=True):
    """User model with FastAPI-Users integration."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "users"

    # Clerk (optional): set when using Clerk for auth; links JWT ``sub`` to this row
    clerk_user_id: str | None = Field(
        default=None,
        sa_column=Column(sa.String(255), nullable=True, unique=True, index=True),
    )

    # FastAPI-Users legacy field: unique internal slug from email local-part at Clerk sync.
    # App UI uses email as handle; editable public creator aliases planned for Business tier.
    username: str = Field(sa_column=Column(sa.String(255), unique=True, nullable=False))

    # Timestamps with timezone
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    last_login_at: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # D026 local legal-acceptance audit (nullable; grandfathered users stay null)
    legal_accepted_at: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="Clerk legal_accepted_at (UTC) recorded at local provision; null for grandfathered users.",
    )
    terms_version: str | None = Field(
        default=None,
        sa_column=Column(sa.String(64), nullable=True),
        description="SMEME_LEGAL_TERMS_VERSION at provision time (config constant; not HTML scrape).",
    )
    privacy_version: str | None = Field(
        default=None,
        sa_column=Column(sa.String(64), nullable=True),
        description="SMEME_LEGAL_PRIVACY_VERSION at provision time (config constant; not HTML scrape).",
    )

    # Creator profile fields (Sprint 6)
    bio: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    website_url: str | None = Field(default=None, sa_column=Column(sa.String(500), nullable=True))
    linkedin_url: str | None = Field(default=None, sa_column=Column(sa.String(500), nullable=True))

    # Credential / reputation fields (Sprint 6)
    credential_level: str = Field(
        default="unverified",
        sa_column=Column(sa.String(30), nullable=False, server_default="unverified", index=True),
    )
    credential_details: str | None = Field(
        default=None, sa_column=Column(sa.String(500), nullable=True)
    )
    show_credential_details: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    # When False, GET /creator/{username} returns 404 (gallery shows username without link).
    creator_page_public: bool = Field(
        default=True,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.true()),
    )
    verified_at: Mapped[datetime | None] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    governance_role: str | None = Field(
        default=None, sa_column=Column(sa.String(50), nullable=True)
    )

    # Stripe billing (Sprint 7)
    stripe_customer_id: str | None = Field(
        default=None, sa_column=Column(sa.String(255), nullable=True)
    )
    stripe_subscription_id: str | None = Field(
        default=None, sa_column=Column(sa.String(255), nullable=True)
    )
    subscription_status: str | None = Field(
        default=None, sa_column=Column(sa.String(30), nullable=True)
    )
    subscription_period_start: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="Stripe current_period_start — Pro usage window start.",
    )
    subscription_period_end: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="Stripe current_period_end — Pro usage resets at this instant.",
    )
    is_premium: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )

    # Downgrade lifecycle (Phase 5 billing sprint)
    subscription_cancel_at_period_end: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    cancellation_explainer_pending: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    cancellation_explainer_acknowledged_at: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    workflow_pick_required: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    live_workflow_root_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    free_usage_epoch: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="Free-tier MCP/wizard metering floor after downgrade resolution.",
    )

    # Relationships
    in_progress_generations: list["InProgressDecisionTreeGeneration"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "passive_deletes": True,
        },
    )


class DecisionTree(BaseSQLModel, table=True):
    """DecisionTree table - stores graph structure and metadata."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "decision_trees"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    author_id: UUID | None = Field(default=None, foreign_key="users.id")
    title: str = Field(index=True)

    # Graph structure stored as JSONB
    graph_data: dict[str, Any] = Field(sa_column=Column(JSONB))  # Nodes, edges, metadata

    # Marketplace gallery flag — column retained; creator Share/Unshare UI/routes removed (2026-06).
    # Product visibility for MCP is mcp_discoverable (Listed), not is_public. Still read/written by:
    # public /gallery, versioning read-only lock (with was_ever_public), interim REST evaluate,
    # creator profile stats, and MCP list metadata. See docs/ARCHITECTURE.md § is_public.
    is_public: bool = Field(
        default=False,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        description="Legacy gallery-public flag; no editor share UI — see ARCHITECTURE.md",
    )
    was_ever_public: bool = Field(
        default=False,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        description="True if this DecisionTree version was ever made public (never reset, even on archive/restore)",
    )

    # Versioning fields
    version_number: int = Field(
        default=1,
        ge=1,
        sa_column_kwargs={"nullable": False},
        description="Incremental version number (v1, v2, v3, etc.)",
    )
    parent_decision_tree_id: UUID | None = Field(
        default=None,
        foreign_key="decision_trees.id",
        sa_column_kwargs={"nullable": True},
        description="Parent version DecisionTree ID (NULL for root versions)",
    )
    is_current: bool = Field(
        default=True,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            index=True,
        ),
        description="Is this the current/latest version in its family?",
    )

    # Archive fields (soft delete)
    is_archived: bool = Field(
        default=False,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        description="Archived decision trees are hidden but preserved for session access",
    )
    archived_at: Mapped[datetime] | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="When this DecisionTree was archived (soft deleted)",
    )

    # Economics-aware metadata — top-level columns for MCP API queryability (Sprint 6)
    intended_audience: str | None = Field(
        default=None, sa_column=Column(sa.String(200), nullable=True)
    )
    use_case: str | None = Field(default=None, sa_column=Column(sa.String(200), nullable=True))
    quality_review_status: str = Field(
        default="unreviewed",
        sa_column=Column(sa.String(30), nullable=False, server_default="unreviewed", index=True),
    )

    # Deterministic symbolic reasoning: null = not compiled; compiled = publish+compile OK
    reasoning_status: str | None = Field(
        default=None,
        sa_column=Column(String(20), nullable=True, index=True),
        description="null | pending | compiled | failed (CHECK in DB)",
    )
    current_artifact_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "reasoning_compiled_artifacts.id",
                ondelete="SET NULL",
                use_alter=True,
                name="fk_decision_trees_current_artifact_id",
            ),
            nullable=True,
            index=True,
        ),
        description="Current ReasoningCompiledArtifact id; append-only history (D025).",
    )

    # MCP tools: opt-in list + evaluate by decision_tree_id (default off)
    mcp_discoverable: bool = Field(
        default=False,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        description="When true, DecisionTree may appear in MCP tool list and be evaluated by id.",
    )
    billing_dormant: bool = Field(
        default=False,
        sa_column=Column(
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        description="Post-downgrade Free tier: download-only; cleared on Pro re-upgrade.",
    )

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Relationships (SQLModel - makes schema explicit)
    # Note: No cascade - sessions are user data and survive DecisionTree deletion
    # Note: lazy="raise" prevents accidental loading. Explicitly use selectinload() when needed.
    sessions: list["DecisionTreeSession"] = Relationship(
        back_populates="decision_tree",
        sa_relationship_kwargs={
            "lazy": "raise",  # Prevents accidental loads and timestamp updates
        },
    )

    # Self-referential relationship for versioning
    # Parent (many-to-one): this decision tree's parent version
    parent: Optional["DecisionTree"] = Relationship(
        sa_relationship_kwargs={
            "remote_side": "DecisionTree.id",  # Points to parent's ID
            "foreign_keys": "DecisionTree.parent_decision_tree_id",  # This decision tree's FK column
            "lazy": "selectin",
            "back_populates": "children",
        }
    )

    # Children (one-to-many): newer versions that have this DecisionTree as parent
    children: list["DecisionTree"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "DecisionTree.parent_decision_tree_id",  # Children's FK points to this decision tree
            "lazy": "selectin",
            "back_populates": "parent",
        }
    )

    research_corpus_row: Optional["DecisionTreeResearchCorpus"] = Relationship(
        back_populates="decision_tree",
        sa_relationship_kwargs={"lazy": "raise", "uselist": False},
    )

    lexicon_draft_row: Optional["DecisionTreeLexiconDraft"] = Relationship(
        back_populates="decision_tree",
        sa_relationship_kwargs={"lazy": "raise", "uselist": False},
    )

    # Helper methods for version management
    def get_version_family(self) -> list["DecisionTree"]:
        """
        Get all versions in this decision tree's family.

        Returns list ordered by version_number.

        Note: This method requires relationships to be eagerly loaded
        (parent and children should be loaded via selectinload).
        """
        # Build family iteratively to avoid recursion issues
        family = {self.id: self}  # Use dict to avoid duplicates
        to_process = [self]

        while to_process:
            current = to_process.pop()

            # Add parent if exists and not already in family
            if current.parent and current.parent.id not in family:
                family[current.parent.id] = current.parent
                to_process.append(current.parent)

            # Add children if exist and not already in family
            # Defensive check: children might be None if not loaded
            if current.children is not None:
                for child in current.children:
                    if child.id not in family:
                        family[child.id] = child
                        to_process.append(child)

        # Convert to list and sort by version number
        return sorted(family.values(), key=lambda q: q.version_number)

    def get_current_version(self) -> "DecisionTree":
        """
        Get the current version in this decision tree's family.

        Returns the DecisionTree marked with is_current=True, or self if none found.
        """
        family = self.get_version_family()
        current = [q for q in family if q.is_current]

        if not current:
            # Fallback: assume highest version number is current
            return max(family, key=lambda q: q.version_number)

        return current[0]

    def get_root_version(self) -> "DecisionTree":
        """Get the root (v1) version in this decision tree's family."""
        root = self
        while root.parent_decision_tree_id and root.parent:
            root = root.parent
        return root

    @property
    def is_outdated(self) -> bool:
        """Check if this DecisionTree is not the current version."""
        return not self.is_current

    @property
    def display_badge(self) -> str:
        """Badge text for UI display."""
        if self.is_public:
            return "🌐 Public"
        return "🔒 Private"


class UserAuditLog(BaseSQLModel, table=True):
    """Append-only audit trail for significant account lifecycle events.

    Rows are never updated after insert.  ``user_id`` is nullable so that
    records survive if the ``users`` row is ever hard-deleted.

    Canonical ``event_type`` values (extend as needed):
      account.deactivated         — legacy; superseded by ``account.deleted`` hard purge
      account.deleted             — user row and owned data hard-deleted
      subscription.cancelled      — Stripe subscription cancelled by SMEme
      subscription.status_changed — Stripe webhook updated subscription status

    Canonical ``actor`` values:
      clerk_webhook   — inbound Clerk ``user.deleted`` event
      stripe_webhook  — inbound Stripe subscription event
      admin           — manual action (future)
    """

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "user_audit_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        description="Nullable so records survive a future hard-delete of the users row",
    )

    event_type: str = Field(
        sa_column=Column(sa.String(50), nullable=False, index=True),
        description="e.g. account.deactivated, subscription.cancelled",
    )
    actor: str = Field(
        sa_column=Column(sa.String(50), nullable=False),
        description="What triggered this event: clerk_webhook, stripe_webhook, admin",
    )
    reason: str = Field(
        sa_column=Column(sa.String(100), nullable=False),
        description="Human-readable cause, e.g. clerk_user_deleted, payment_failed",
    )
    event_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        description="Arbitrary context: clerk_user_id, stripe_sub_id, old/new status, etc.",
    )

    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


class AccountDeletionFailure(BaseSQLModel, table=True):
    """Dead-letter queue for account purge failures (webhook retry / ops sweeper)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "account_deletion_failures"
    __table_args__ = (
        Index(
            "ix_account_deletion_failures_unresolved_clerk",
            "clerk_user_id",
            postgresql_where=sa.text("resolved_at IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), nullable=True, index=True),
        description="Local user id at failure time; may be null after partial purge",
    )
    clerk_user_id: str | None = Field(
        default=None,
        sa_column=Column(sa.String(255), nullable=True, index=True),
    )
    error_message: str = Field(sa_column=Column(Text, nullable=False))
    attempt_count: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    resolved_at: Mapped[datetime | None] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


class ReasoningCompiledArtifact(BaseSQLModel, table=True):
    """Persisted validated IR artifact; append-only history per DecisionTree (D025)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "reasoning_compiled_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "decision_tree_id", name="uq_reasoning_compiled_artifacts_id_tree"),
        Index(
            "uq_reasoning_compiled_artifacts_tree_version",
            "decision_tree_id",
            "artifact_version",
            unique=True,
            postgresql_where=sa.text("artifact_version IS NOT NULL"),
            sqlite_where=sa.text("artifact_version IS NOT NULL"),
        ),
        Index(
            "uq_reasoning_compiled_artifacts_tree_orphan",
            "decision_tree_id",
            unique=True,
            postgresql_where=sa.text("artifact_version IS NULL"),
            sqlite_where=sa.text("artifact_version IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    decision_tree_id: UUID = Field(
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Owning DecisionTree; multiple immutable rows allowed (D025).",
    )
    ir_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    graph_hash: str = Field(sa_column=Column(String(64), nullable=False))
    compiler_version: str = Field(sa_column=Column(String(20), nullable=False))
    ir_format_version: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    cevi_contract_json: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="PublishedEvidenceContract JSON; written on successful publish.",
    )
    cevi_contract_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="SHA-256 hex over canonical cevi_contract_json.",
    )
    research_corpus_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="SHA-256 hex of UTF-8 corpus bytes used for this compile.",
    )
    ir_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="SHA-256 of canonical ir_json; null only for unadoptable pre-D025 orphans.",
    )
    artifact_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="D025 v1 content identity digest; null only for unadoptable orphans.",
    )
    artifact_version: int | None = Field(
        default=None,
        sa_column=Column(sa.BigInteger(), nullable=True),
        description="Per-tree deploy vintage (starts at 1); null only for unadoptable orphans.",
    )
    compiled_at: Mapped[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), server_default=sa.func.now()),
    )


class DecisionTreeResearchCorpus(BaseSQLModel, table=True):
    """SME research text persisted for Deploy-time evidence-contract induction (not read on evaluate hot path)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "decision_tree_research_corpora"

    decision_tree_id: UUID = Field(
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    body_text: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
        description="Normalized UTF-8 research corpus (paste + merged generation notes).",
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    decision_tree: Optional["DecisionTree"] = Relationship(
        back_populates="research_corpus_row",
        sa_relationship_kwargs={"lazy": "raise"},
    )


class DecisionTreeLexiconDraft(BaseSQLModel, table=True):
    """Author Lexicon draft: NL glosses keyed by atom_id in ``body_json`` (validated at save/publish)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "decision_tree_lexicon_drafts"

    decision_tree_id: UUID = Field(
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    body_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        description="Draft lexicon entries keyed by canonical atom id (not shown in author UI).",
    )
    lexicon_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="SHA-256 hex of canonical JSON for body_json at last save (provenance; do not hash raw dict key order).",
    )
    graph_hash_at_save: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
        description="Graph hash when draft was last saved; used for stale detection.",
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    decision_tree: Optional["DecisionTree"] = Relationship(
        back_populates="lexicon_draft_row",
        sa_relationship_kwargs={"lazy": "raise", "uselist": False},
    )


class ReasoningEvaluationRun(BaseSQLModel, table=True):
    """One persisted reasoning evaluate call (audit + outcome)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "reasoning_evaluation_runs"
    __table_args__ = (
        Index(
            "ix_reasoning_evaluation_runs_decision_tree_created", "decision_tree_id", "created_at"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    decision_tree_id: UUID = Field(
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("decision_tree_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    caller_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    outcome: str = Field(sa_column=Column(String(20), nullable=False, index=True))

    evidence_items: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    conflict_report: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    user_resolutions: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    final_facts: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    permissive_mode: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )

    explanation: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    triggered_edges: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    minimal_repairs: list[Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    ingest_warnings: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        description="Non-blocking ingest / provenance warnings at evaluate time.",
    )
    report: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        description="Product-facing evaluation report (server-generated memo).",
    )
    ingest_envelope: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="Provenance ingest snapshot (answers + evidence) at evaluate time.",
    )

    artifact_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("reasoning_compiled_artifacts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        description="Compiled artifact used for this evaluation.",
    )
    artifact_version: int | None = Field(
        default=None,
        sa_column=Column(sa.BigInteger(), nullable=True),
    )
    artifact_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    artifact_graph_hash: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    compiled_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_at: Mapped[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), server_default=sa.func.now()),
    )


class InquirySession(BaseSQLModel, table=True):
    """Durable Inquire case: ANALYZE preimage only (Phase 6). Not DecisionTreeSession."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "inquiry_sessions"
    __table_args__ = (
        Index("ix_inquiry_sessions_owner_status", "owner_user_id", "status"),
        Index("ix_inquiry_sessions_tree_created", "decision_tree_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    decision_tree_id: UUID = Field(
        sa_column=Column(
            ForeignKey("decision_trees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    # FrozenArtifactSnapshot (nullable FK; identity + catalog are authoritative)
    artifact_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("reasoning_compiled_artifacts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        description="Navigation to compiled row; SET NULL on delete. Execution needs matching row.",
    )
    artifact_identity: str = Field(
        sa_column=Column(String(64), nullable=False),
        description="D025 artifact_hash frozen at start; never retargeted.",
    )
    worksheet_catalog: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
        description="Frozen extractor vocabulary; never rebuilt from live graph_data.",
    )
    pv_version: str = Field(sa_column=Column(String(255), nullable=False))
    assumptions: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        description="Pinned φ: force_reachable_ids / force_unreachable_ids.",
    )
    status: str = Field(
        sa_column=Column(String(20), nullable=False, index=True),
        description="ACTIVE | STOPPED | ABANDONED",
    )
    stop_reason: str | None = Field(
        default=None,
        sa_column=Column(String(80), nullable=True),
        description=(
            "Inquire ANALYZE stop_reason when status=STOPPED "
            "(e.g. verified_resolved_consequence, resolving_support_incomplete, "
            "operational_budget). Chat may still expose an Apply report alongside."
        ),
    )
    revision: int = Field(
        default=1,
        sa_column=Column(sa.BigInteger(), nullable=False, server_default="1"),
        description="Option A: version(E, verified, assumptions, status).",
    )
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    stopped_at: Mapped[datetime] | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class InquiryAdmittedAssertion(BaseSQLModel, table=True):
    """Live admitted (q, a, p) for one inquiry session."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "inquiry_admitted_assertions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "question_id",
            name="uq_inquiry_admitted_assertions_session_question",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("inquiry_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    question_id: str = Field(sa_column=Column(String(255), nullable=False))
    option: str = Field(sa_column=Column(String(512), nullable=False))
    provenance_id: str = Field(sa_column=Column(String(512), nullable=False))


class InquiryVerifiedAssertion(BaseSQLModel, table=True):
    """Server-issued VerificationKey retained under session-pinned pv_version."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "inquiry_verified_assertions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "artifact_identity",
            "question_id",
            "option",
            "provenance_identity",
            "pv_version",
            name="uq_inquiry_verified_assertions_key",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("inquiry_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    artifact_identity: str = Field(sa_column=Column(String(64), nullable=False))
    question_id: str = Field(sa_column=Column(String(255), nullable=False))
    option: str = Field(sa_column=Column(String(512), nullable=False))
    provenance_identity: str = Field(sa_column=Column(String(512), nullable=False))
    pv_version: str = Field(sa_column=Column(String(255), nullable=False))


class InquiryMutationReceipt(BaseSQLModel, table=True):
    """Idempotency receipt for admit/verify (request_hash + response)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "inquiry_mutation_receipts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_inquiry_mutation_receipts_session_key",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("inquiry_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    operation: str = Field(sa_column=Column(String(32), nullable=False))
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    response_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


class InquirySessionEvent(BaseSQLModel, table=True):
    """Append-only audit for an inquiry session (not ANALYZE input)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "inquiry_session_events"
    __table_args__ = (
        Index("ix_inquiry_session_events_session_created", "session_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("inquiry_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    revision: int = Field(sa_column=Column(sa.BigInteger(), nullable=False))
    receipt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("inquiry_mutation_receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


class DecisionTreeSession(BaseSQLModel, table=True):
    """User session for completing a DecisionTree."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "decision_tree_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    decision_tree_id: UUID = Field(foreign_key="decision_trees.id", index=True)

    # Navigation state
    current_node_id: str | None = Field(default=None, description="Current question being shown")

    # User responses stored as JSONB
    user_responses: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
        description="User answers by node ID",
    )

    # Conclusion tracking (new field for conclusion nodes feature)
    conclusion_reached: str | None = Field(
        default=None,
        sa_column_kwargs={"nullable": True},
        description="ID of the conclusion node reached (if any)",
    )

    # Session tracking (timezone-aware)
    started_at: Mapped[datetime] | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
        description="When user started the DecisionTree (first answer)",
    )
    completed_at: Mapped[datetime] | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
        description="When DecisionTree was completed",
    )

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    updated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Relationships (SQLModel - makes schema explicit)
    decision_tree: "DecisionTree" = Relationship(back_populates="sessions")
    memos: list["Memo"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        },
    )


class Memo(BaseSQLModel, table=True):
    """Generated memo from DecisionTree session."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "memos"

    # Primary key
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Foreign keys
    session_id: UUID = Field(foreign_key="decision_tree_sessions.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)

    # Memo content
    title: str = Field(max_length=500, nullable=False)
    summary: str = Field(sa_column=Column(Text, nullable=False))
    recommendations: str = Field(sa_column=Column(Text, nullable=False))

    # Optional: Store raw LLM response for debugging
    llm_response: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )

    # Timestamps (timezone-aware)
    generated_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Relationships (SQLModel - makes schema explicit)
    session: "DecisionTreeSession" = Relationship(back_populates="memos")
