"""Per-user sample decision tree (Deployed + Listed). One helper, two doors.

Do not call until a local ``User`` exists (Clerk email verification + express
ToS/Privacy on new provision). Web signup does not auto-seed; the dashboard
**Load sample** button is the web door. The first empty MCP list calls this
helper so ``smeme_reasoning_list`` returns a usable tree.
"""

from __future__ import annotations

import json
import logging
from importlib.resources import files
from typing import Any, TypedDict, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, User
from smeme.decision_tree.deploy import DeployNotReadyError, compile_and_persist_current_graph
from smeme.decision_tree.models import DTGraph
from smeme.reasoning.artifact_deploy import load_current_compiled_artifact
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state

logger = logging.getLogger(__name__)


class SampleFixture(TypedDict):
    sample_key: str
    title: str
    canned_raw_answers: dict[str, str]
    expected_conclusion_id: str
    expected_result_kind: str
    graph: dict[str, Any]


def _load_fixture() -> SampleFixture:
    fixture_path = files("smeme.decision_tree").joinpath(
        "fixtures",
        "smeme_sample_v1.json",
    )
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("SMEme sample fixture must be a JSON object")
    fixture = cast(SampleFixture, raw)
    DTGraph.model_validate(fixture["graph"])
    return fixture


SAMPLE_FIXTURE = _load_fixture()
SAMPLE_KEY = SAMPLE_FIXTURE["sample_key"]
SAMPLE_TITLE = SAMPLE_FIXTURE["title"]
CANNED_RAW_ANSWERS = dict(SAMPLE_FIXTURE["canned_raw_answers"])
EXPECTED_CONCLUSION_ID = SAMPLE_FIXTURE["expected_conclusion_id"]
EXPECTED_RESULT_KIND = SAMPLE_FIXTURE["expected_result_kind"]


class SampleTreeError(RuntimeError):
    """User-facing failure from ``ensure_sample_tree`` (quota or Deploy gate)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def sample_graph() -> DTGraph:
    """Tiny sanitised fixture: not legal advice, no real client names."""
    return DTGraph.model_validate(SAMPLE_FIXTURE["graph"])


async def find_sample_tree(db: AsyncSession, user_id: Any) -> DecisionTree | None:
    result = await db.execute(
        select(DecisionTree).where(
            DecisionTree.author_id == user_id,
            DecisionTree.sample_key == SAMPLE_KEY,
        )
    )
    return result.scalar_one_or_none()


async def _make_live_and_listed(db: AsyncSession, tree: DecisionTree) -> DecisionTree:
    if not tree.is_current or tree.is_archived:
        tree.is_current = True
        tree.is_archived = False
        tree.archived_at = None
        db.add(tree)
    artifact = await load_current_compiled_artifact(db, tree)
    if reasoning_tools_row_state(tree, artifact) != "live":
        await compile_and_persist_current_graph(db, tree)
    if not tree.mcp_discoverable:
        tree.mcp_discoverable = True
        db.add(tree)
    await db.flush()
    return tree


async def ensure_sample_tree(user: User | None, db: AsyncSession) -> DecisionTree | None:
    """Idempotent: one sample tree per user, Deployed + Listed, owned by that user.

    Returns ``None`` when there is no ``User`` (caller must not seed before
    provision). Raises ``SampleTreeError`` on quota or Deploy failure.
    """
    if user is None or getattr(user, "id", None) is None:
        return None
    user_id = user.id

    existing = await find_sample_tree(db, user_id)
    if existing is not None:
        tree = await _make_live_and_listed(db, existing)
        await db.commit()
        await db.refresh(tree)
        return tree

    from smeme.billing.quota import QuotaDimension, check_quota

    quota = await check_quota(db, user, QuotaDimension.DECISION_TREES, projected_add=1.0)
    if not quota.allowed:
        raise SampleTreeError("quota_exceeded", quota.message)

    graph = sample_graph()
    tree = DecisionTree(
        author_id=user_id,
        title=SAMPLE_TITLE,
        sample_key=SAMPLE_KEY,
        graph_data=graph.model_dump(mode="json"),
        is_public=False,
        is_current=True,
        is_archived=False,
        mcp_discoverable=False,
    )
    db.add(tree)
    try:
        await db.flush()
    except IntegrityError:
        # Another first-list/dashboard request won the per-user sample race.
        await db.rollback()
        winner = await find_sample_tree(db, user_id)
        if winner is None:
            raise
        tree = await _make_live_and_listed(db, winner)
        await db.commit()
        await db.refresh(tree)
        return tree

    try:
        await compile_and_persist_current_graph(db, tree)
    except DeployNotReadyError as exc:
        await db.rollback()
        logger.error(
            "Sample tree failed Deploy gate",
            extra={"user_id": str(user_id), "ready": exc.readiness.ready},
        )
        raise SampleTreeError(
            "deploy_failed",
            "The sample decision tree could not be Deployed. Try again, or create a tree in the editor.",
        ) from exc

    tree.mcp_discoverable = True
    db.add(tree)
    await db.commit()
    await db.refresh(tree)
    logger.info(
        "Ensured sample decision tree",
        extra={"user_id": str(user_id), "decision_tree_id": str(tree.id)},
    )
    return tree
