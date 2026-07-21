"""Authentication backends for FastAPI-Users."""

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)

from smeme.core.config import settings

# Token lifetime: 7 days in seconds
TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60  # 604800

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """Get JWT strategy with configuration."""
    return JWTStrategy(
        secret=settings.jwt_secret_key,
        lifetime_seconds=TOKEN_LIFETIME_SECONDS,
        algorithm=settings.algorithm,
    )


auth_backend_bearer = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# Cookie transport with environment-aware secure + SameSite
# Production (HTTPS): SameSite=None so cookies survive Stripe redirect; Secure=True required
# Development: SameSite=Lax (SameSite=None requires Secure, which needs HTTPS)
cookie_transport = CookieTransport(
    cookie_name="session",
    cookie_secure=settings.is_production,
    cookie_samesite="none" if settings.is_production else "lax",
)

auth_backend_cookie = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

# For legacy imports elsewhere in the codebase now point to cookie backend
auth_backend = auth_backend_cookie
