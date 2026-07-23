"""Unit tests share the root session-scoped asyncio/database fixtures.

Do not override ``event_loop`` here: database-backed unit tests reuse the
session-scoped async engine, and a nested function-scoped loop corrupts
asyncpg connections with "Future attached to a different loop" failures.
"""
