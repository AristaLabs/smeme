"""Caching helpers for DTGraphs using aiocache."""

from uuid import UUID

from aiocache import Cache
from aiocache.serializers import PickleSerializer

from smeme.qnr.models import DTGraph

# In-memory cache for DTGraphs (1 hour TTL)
# TODO: Move to Redis when scaling
qnr_cache = Cache(
    Cache.MEMORY,
    serializer=PickleSerializer(),
    ttl=3600,  # 1 hour
    namespace="dt_graphs",
)


async def get_cached_graph(qnr_id: UUID) -> DTGraph | None:
    """
    Get DTGraph from cache.

    Args:
        qnr_id: QNR UUID

    Returns:
        Cached DTGraph or None if not in cache
    """
    key = f"graph_{str(qnr_id)}"
    return await qnr_cache.get(key)


async def cache_graph(qnr_id: UUID, graph: DTGraph) -> None:
    """
    Cache DTGraph.

    Args:
        qnr_id: QNR UUID
        graph: DTGraph to cache
    """
    key = f"graph_{str(qnr_id)}"
    await qnr_cache.set(key, graph)


async def invalidate_graph_cache(qnr_id: UUID) -> None:
    """
    Invalidate cached graph (call when QNR is updated).

    Args:
        qnr_id: QNR UUID
    """
    key = f"graph_{str(qnr_id)}"
    await qnr_cache.delete(key)


async def clear_all_graph_cache() -> None:
    """Clear entire DTGraph cache."""
    await qnr_cache.clear()
