"""Shared auth constants (avoid circular imports between routes and clerk_auth)."""

RESERVED_USERNAMES = frozenset(
    {
        "gallery",
        "marketplace",
        "auth",
        "admin",
        "api",
        "creator",
        "qnr",
        "memo",
        "settings",
        "billing",
        "dashboard",
        "login",
        "register",
        "logout",
        "verify",
        "reset-password",
        "forgot-password",
    }
)
