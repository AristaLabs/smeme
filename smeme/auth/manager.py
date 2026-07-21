"""User manager for FastAPI-Users (Clerk sync layer; no HTML auth flows)."""

from uuid import UUID

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.config import settings
from smeme.core.database import get_db
from smeme.core.logging import get_logger
from smeme.core.models import User

logger = get_logger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    """User manager for local ``User`` rows synced from Clerk."""

    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key

    async def on_after_register(self, user: User, request: Request | None = None):
        """Legacy FastAPI-Users hook — registration is Clerk-managed."""
        logger.info("User %s registered (Clerk-managed sign-up)", user.id)

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response=None,
    ):
        """Called after user login."""
        logger.info("User %s logged in", user.id)


async def get_user_db(session: AsyncSession = Depends(get_db)):
    """Get user database adapter."""
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    """Get user manager instance."""
    yield UserManager(user_db)
