"""Uvicorn target for the Core product image (no SaaS overlay).

Usage::

    uvicorn smeme.core_entrypoint:app --host 0.0.0.0 --port 8000
"""

from smeme.app_factory import create_core_app

app = create_core_app(include_product_root=True)
