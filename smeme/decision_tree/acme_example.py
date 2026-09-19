"""Opt-in, per-account ACME LangGraph demonstration fixture.

This helper is intentionally separate from the generic sample tree and its
first-empty-MCP-list provisioning path. Callers must opt in explicitly.
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
from smeme.reasoning.graph_hash import canonical_graph_hash

logger = logging.getLogger(__name__)


class AcmeExampleFixture(TypedDict):
    sample_key: str
    title: str
    fictional_demo_disclaimer: str
    source_graph_hash: str
    public_graph_hash: str
    graph: dict[str, Any]


def _load_fixture() -> AcmeExampleFixture:
    fixture_path = files("smeme.decision_tree").joinpath(
        "fixtures",
        "smeme_acme_xborder_withholding_v1.json",
    )
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("ACME example fixture must be a JSON object")
    fixture = cast(AcmeExampleFixture, raw)
    graph = DTGraph.model_validate(fixture["graph"])
    actual_hash = canonical_graph_hash(graph)
    if actual_hash != fixture["public_graph_hash"]:
        message = (
            "ACME example fixture graph hash mismatch: "
            f"expected {fixture['public_graph_hash']}, got {actual_hash}"
        )
        raise RuntimeError(message)
    return fixture


ACME_EXAMPLE_FIXTURE = _load_fixture()
ACME_EXAMPLE_SAMPLE_KEY = ACME_EXAMPLE_FIXTURE["sample_key"]
ACME_EXAMPLE_TITLE = ACME_EXAMPLE_FIXTURE["title"]
ACME_EXAMPLE_DISCLAIMER = ACME_EXAMPLE_FIXTURE["fictional_demo_disclaimer"]
ACME_EXAMPLE_SOURCE_GRAPH_HASH = ACME_EXAMPLE_FIXTURE["source_graph_hash"]
ACME_EXAMPLE_PUBLIC_GRAPH_HASH = ACME_EXAMPLE_FIXTURE["public_graph_hash"]


class AcmeExampleError(RuntimeError):
    """User-facing failure while loading the ACME account fixture."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def acme_example_graph() -> DTGraph:
    """Return the validated canonical ACME demonstration graph."""
    return DTGraph.model_validate(ACME_EXAMPLE_FIXTURE["graph"])


async def find_acme_example_tree(
    db: AsyncSession,
    user_id: Any,
) -> DecisionTree | None:
    """Find only the durable ACME fixture owned by ``user_id``."""
    result = await db.execute(
        select(DecisionTree).where(
            DecisionTree.author_id == user_id,
            DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
        )
    )
    return result.scalar_one_or_none()


async def _ensure_live_and_listed(
    db: AsyncSession,
    tree: DecisionTree,
) -> DecisionTree:
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


async def _check_slot_quota(
    db: AsyncSession,
    user: User,
) -> None:
    from smeme.billing.quota import QuotaDimension, check_quota

    quota = await check_quota(db, user, QuotaDimension.DECISION_TREES, projected_add=1.0)
    if not quota.allowed:
        raise AcmeExampleError("quota_exceeded", quota.message)


def _deploy_error(exc: DeployNotReadyError) -> AcmeExampleError:
    return AcmeExampleError(
        "deploy_failed",
        "The ACME example could not be Deployed. Try again later.",
    )


async def ensure_acme_example_tree(
    user: User | None,
    db: AsyncSession,
) -> DecisionTree | None:
    """Create, Deploy, and List one canonical ACME fixture for this account.

    Reusing an active fixture consumes no additional decision-tree slot.
    Restoring an archived fixture does consume a slot and is quota checked.
    """
    if user is None or getattr(user, "id", None) is None:
        return None
    user_id = user.id

    existing = await find_acme_example_tree(db, user_id)
    if existing is not None:
        if not existing.is_current or existing.is_archived:
            await _check_slot_quota(db, user)
        try:
            tree = await _ensure_live_and_listed(db, existing)
        except DeployNotReadyError as exc:
            await db.rollback()
            logger.error(
                "Existing ACME example failed Deploy gate",
                extra={"user_id": str(user_id), "ready": exc.readiness.ready},
            )
            raise _deploy_error(exc) from exc
        await db.commit()
        await db.refresh(tree)
        return tree

    await _check_slot_quota(db, user)
    graph = acme_example_graph()
    tree = DecisionTree(
        author_id=user_id,
        title=ACME_EXAMPLE_TITLE,
        sample_key=ACME_EXAMPLE_SAMPLE_KEY,
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
        # A concurrent opt-in request won the per-account fixture race.
        await db.rollback()
        winner = await find_acme_example_tree(db, user_id)
        if winner is None:
            raise
        try:
            tree = await _ensure_live_and_listed(db, winner)
        except DeployNotReadyError as exc:
            await db.rollback()
            raise _deploy_error(exc) from exc
        await db.commit()
        await db.refresh(tree)
        return tree

    try:
        await compile_and_persist_current_graph(db, tree)
    except DeployNotReadyError as exc:
        await db.rollback()
        logger.error(
            "ACME example failed Deploy gate",
            extra={"user_id": str(user_id), "ready": exc.readiness.ready},
        )
        raise _deploy_error(exc) from exc

    tree.mcp_discoverable = True
    db.add(tree)
    await db.commit()
    await db.refresh(tree)
    logger.info(
        "Ensured ACME example decision tree",
        extra={"user_id": str(user_id), "decision_tree_id": str(tree.id)},
    )
    return tree
