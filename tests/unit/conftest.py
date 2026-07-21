"""Minimal conftest for pure unit tests.

No database, no async fixtures, no event loop manipulation.
These tests are synchronous and don't need any special infrastructure.
"""

import pytest


# Override the session-scoped event_loop from parent conftest
# by providing a function-scoped one (or None for sync tests)
@pytest.fixture(scope="function")
def event_loop():
    """Provide a function-scoped event loop for this directory.

    This overrides the session-scoped event_loop from tests/conftest.py,
    preventing scope mismatch issues for synchronous tests.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
