"""Caching helpers for QNR graphs using aiocache."""

from uuid import UUID

from aiocache import Cache
from aiocache.serializers import PickleSerializer

from smeme.qnr.models import QNRGraph

# In-memory cache for QNR graphs (1 hour TTL)
# TODO: Move to Redis when scaling
qnr_cache = Cache(
    Cache.MEMORY,
    serializer=PickleSerializer(),
    ttl=3600,  # 1 hour
    namespace="qnr_graphs",
)


async def get_cached_graph(qnr_id: UUID) -> QNRGraph | None:
    """
    Get QNR graph from cache.

    Args:
        qnr_id: QNR UUID

    Returns:
        Cached QNRGraph or None if not in cache
    """
    key = f"graph_{str(qnr_id)}"
    return await qnr_cache.get(key)


async def cache_graph(qnr_id: UUID, graph: QNRGraph) -> None:
    """
    Cache QNR graph.

    Args:
        qnr_id: QNR UUID
        graph: QNRGraph to cache
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
    """Clear entire QNR graph cache."""
    await qnr_cache.clear()
