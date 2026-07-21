"""FastAPI-Users setup and Clerk auth dependencies."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi import status as http_status
from fastapi_users import FastAPIUsers
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.backend import auth_backend_bearer, auth_backend_cookie
from smeme.auth.clerk_auth import clerk_authenticated_user
from smeme.auth.manager import UserManager, get_user_manager
from smeme.core.database import get_db
from smeme.core.models import User

fastapi_users = FastAPIUsers[User, UUID](
    get_user_manager,
    [auth_backend_cookie, auth_backend_bearer],
)


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
) -> User | None:
    return await clerk_authenticated_user(request, db, user_manager)


async def get_current_active_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    user = await get_current_user_optional(request, db, user_manager)
    if user is None:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Inactive account",
        )
    return user


async def get_current_active_verified_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    user = await get_current_active_user(request, db, user_manager)
    if not user.is_verified:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )
    return user


async def get_current_superuser(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    user = await get_current_active_user(request, db, user_manager)
    if not user.is_superuser:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return user


current_active_user = get_current_active_user
current_active_verified_user = get_current_active_verified_user
current_superuser = get_current_superuser
