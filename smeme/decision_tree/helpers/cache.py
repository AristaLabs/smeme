"""Caching helpers for DecisionTree graphs using aiocache."""

from uuid import UUID

from aiocache import Cache
from aiocache.serializers import PickleSerializer

from smeme.decision_tree.models import DTGraph

# In-memory cache for DecisionTree graphs (1 hour TTL)
# TODO: Move to Redis when scaling
decision_tree_cache = Cache(
    Cache.MEMORY,
    serializer=PickleSerializer(),
    ttl=3600,  # 1 hour
    namespace="dt_graphs",
)


async def get_cached_graph(decision_tree_id: UUID) -> DTGraph | None:
    """
    Get DecisionTree graph from cache.

    Args:
        decision_tree_id: DecisionTree UUID

    Returns:
        Cached DTGraph or None if not in cache
    """
    key = f"graph_{str(decision_tree_id)}"
    return await decision_tree_cache.get(key)


async def cache_graph(decision_tree_id: UUID, graph: DTGraph) -> None:
    """
    Cache DecisionTree graph.

    Args:
        decision_tree_id: DecisionTree UUID
        graph: DTGraph to cache
    """
    key = f"graph_{str(decision_tree_id)}"
    await decision_tree_cache.set(key, graph)


async def invalidate_graph_cache(decision_tree_id: UUID) -> None:
    """
    Invalidate cached graph (call when DecisionTree is updated).

    Args:
        decision_tree_id: DecisionTree UUID
    """
    key = f"graph_{str(decision_tree_id)}"
    await decision_tree_cache.delete(key)


async def clear_all_graph_cache() -> None:
    """Clear entire DecisionTree graph cache."""
    await decision_tree_cache.clear()
