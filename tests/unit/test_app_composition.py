"""Tests for Core app composition (D023). SaaS overlay covered separately."""

from __future__ import annotations

from smeme.app_factory import create_core_app


def _route_paths(app) -> set[str]:
    """Collect mounted paths, including FastAPI 0.140+ ``_IncludedRouter`` nests."""
    paths: set[str] = set()

    def walk(routes, prefix: str = "") -> None:
        for route in routes:
            route_path = getattr(route, "path", None)
            if isinstance(route_path, str):
                paths.add(f"{prefix}{route_path}" if prefix else route_path)

            included = getattr(route, "original_router", None)
            if included is not None:
                include_prefix = ""
                ctx = getattr(route, "include_context", None)
                if ctx is not None:
                    include_prefix = getattr(ctx, "prefix", "") or ""
                walk(included.routes, f"{prefix}{include_prefix}")
                continue

            nested = getattr(route, "routes", None)
            if nested is not None:
                walk(nested, f"{prefix}{route_path or ''}")

    walk(app.routes)
    return paths


def _middleware_names(app) -> set[str]:
    return {middleware.cls.__name__ for middleware in app.user_middleware}


def test_core_app_omits_saas_only_routes() -> None:
    app = create_core_app(include_product_root=True)
    paths = _route_paths(app)
    assert "/how-it-works" not in paths
    assert "/marketplace/business" not in paths
    assert any(p.startswith("/billing") or p == "/billing" for p in paths) is False
    assert "/decision-trees/dashboard" in paths or any("/dashboard" in p for p in paths)
    assert app.state.smeme_distro == "core"
    assert app.state.quota_policy == "unlimited_metered"
    assert "WorkflowPickRequiredMiddleware" not in _middleware_names(app)
    # Core owns /
    assert "/" in paths
