"""Tests for Core app composition (D023). SaaS overlay covered separately."""

from __future__ import annotations

from smeme.app_factory import create_core_app


def _route_paths(app) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def _middleware_names(app) -> set[str]:
    return {middleware.cls.__name__ for middleware in app.user_middleware}


def test_core_app_omits_saas_only_routes() -> None:
    app = create_core_app(include_product_root=True)
    paths = _route_paths(app)
    assert "/how-it-works" not in paths
    assert "/marketplace/business" not in paths
    assert any(p.startswith("/billing") or p == "/billing" for p in paths) is False
    assert "/qnr/dashboard" in paths or any("/dashboard" in p for p in paths)
    assert app.state.smeme_distro == "core"
    assert "WorkflowPickRequiredMiddleware" not in _middleware_names(app)
    # Core owns /
    assert "/" in paths
