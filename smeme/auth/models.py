"""Authentication models using FastAPI-Users."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi_users import schemas
from pydantic import EmailStr, field_validator


class UserRead(schemas.BaseUser[UUID]):
    """User read schema for API responses."""

    username: str
    bio: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    credential_level: str = "unverified"
    credential_details: str | None = None
    show_credential_details: bool = False
    verified_at: datetime | None = None
    governance_role: str | None = None
    is_premium: bool = False
    creator_page_public: bool = True


class UserCreate(schemas.BaseUserCreate):
    """User creation schema."""

    username: str
    email: EmailStr
    password: str


class UserUpdate(schemas.BaseUserUpdate):
    """User update schema — SMEme-owned fields only.

    email and password are excluded: both are managed by Clerk.
    credential_level, verified_at, governance_role are superuser-only.
    """

    username: str | None = None
    bio: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    credential_details: str | None = None
    show_credential_details: bool | None = None
    creator_page_public: bool | None = None

    @field_validator("website_url", "linkedin_url")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        """Only render externally navigable creator links with safe URL schemes."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlsplit(stripped)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must start with http:// or https://")
        return stripped
