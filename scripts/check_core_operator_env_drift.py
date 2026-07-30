#!/usr/bin/env python3
"""Fail when Core operator compose keys drift from docs / Settings aliases.

Canonical operator keys are those forwarded under ``services.web.environment``
in ``docker-compose.core.yml`` (plus compose-only ``SMEME_CORE_IMAGE`` /
``POSTGRES_PASSWORD`` / ``SMEME_PUBLIC_HOST`` for prod). Cloud-only Settings
aliases (Stripe, Plausible, SendGrid waitlist, MCP COGS, Render) must not
appear in the operator compose surface.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.core.yml"
COMPOSE_PROD = ROOT / "docker-compose.core.prod.yml"
ENV_EXAMPLE = ROOT / ".env.core.example"
ENV_GUIDE = ROOT / "docs" / "guides" / "self-host-env.md"
CONFIG = ROOT / "smeme" / "core" / "config.py"

# Compose-only keys (not Settings Field aliases).
COMPOSE_ONLY = frozenset(
    {
        "SMEME_CORE_IMAGE",
        "POSTGRES_PASSWORD",
        "SMEME_PUBLIC_HOST",
    }
)

# Settings aliases that must never be Core compose operator knobs.
CLOUD_ONLY_FORBIDDEN = frozenset(
    {
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PREMIUM_PRICE_ID",
        "PLAUSIBLE_DOMAIN",
        "PLAUSIBLE_SCRIPT_URL",
        "SENDGRID_API_KEY",
        "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_NAME",
        "TEAMS_WAITLIST_NOTIFY_EMAIL",
        "MCP_COST_BASELINE_USD_MICROS",
        "MCP_COST_USD_MICROS_PER_SECOND",
        "RENDER_EXTERNAL_URL",
        "RENDER_GIT_COMMIT",
        "RENDER_GIT_BRANCH",
        "RENDER_SERVICE_NAME",
    }
)

# Profiles that must be documented in self-host-env.md.
REQUIRED_PROFILES = (
    "profile-health",
    "profile-mcp-reasoning",
    "profile-mcp-authoring",
    "profile-wizard",
    "profile-full-pilot",
)

_ENV_LINE = re.compile(
    r"^\s*(?:-\s+)?([A-Z][A-Z0-9_]*)\s*:",
    re.MULTILINE,
)
_ALIAS = re.compile(r'alias\s*=\s*"([A-Z][A-Z0-9_]*)"')


def _compose_web_keys(text: str) -> set[str]:
    """Extract environment keys under the web service only."""
    # Slice from "  web:" through next top-level service or volumes.
    m = re.search(r"(?ms)^  web:\n(.*?)(?=^  [a-z]|^volumes:|\Z)", text)
    if not m:
        raise SystemExit("docker-compose.core.yml: could not find services.web")
    web = m.group(1)
    env_m = re.search(r"(?ms)^\s{4}environment:\n(.*?)(?=^\s{4}[a-z]|\Z)", web)
    if not env_m:
        raise SystemExit("docker-compose.core.yml: web.environment missing")
    keys = set(_ENV_LINE.findall(env_m.group(1)))
    # DATABASE_URL is composed from POSTGRES_PASSWORD; still an operator-facing key.
    return keys


def _mentioned(path: Path, key: str) -> bool:
    return key in path.read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    for path in (COMPOSE, COMPOSE_PROD, ENV_EXAMPLE, ENV_GUIDE, CONFIG):
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    compose_text = COMPOSE.read_text(encoding="utf-8")
    web_keys = _compose_web_keys(compose_text)
    # Image is required at service level, not always under environment.
    if "image:" in compose_text and "SMEME_CORE_IMAGE" in compose_text:
        operator_keys = set(web_keys) | {"SMEME_CORE_IMAGE", "POSTGRES_PASSWORD"}
    else:
        errors.append("compose must reference SMEME_CORE_IMAGE for pull-only path")
        operator_keys = set(web_keys) | {"POSTGRES_PASSWORD"}

    prod_text = COMPOSE_PROD.read_text(encoding="utf-8")
    if "SMEME_PUBLIC_HOST" not in prod_text:
        errors.append("docker-compose.core.prod.yml must forward SMEME_PUBLIC_HOST to Caddy")

    settings_aliases = set(_ALIAS.findall(CONFIG.read_text(encoding="utf-8")))

    for key in sorted(CLOUD_ONLY_FORBIDDEN & web_keys):
        errors.append(f"Cloud-only key forwarded in compose web.environment: {key}")

    for key in sorted(operator_keys):
        if key in COMPOSE_ONLY:
            continue
        if key not in settings_aliases and key != "DATABASE_URL":
            # DATABASE_URL is Settings; ensure present
            if key == "DATABASE_URL":
                continue
            errors.append(f"compose forwards {key} but Settings has no matching alias")
        if key == "DATABASE_URL":
            if key not in settings_aliases:
                errors.append("DATABASE_URL missing from Settings aliases")
            continue
        if not _mentioned(ENV_EXAMPLE, key):
            errors.append(f".env.core.example does not mention {key}")
        if not _mentioned(ENV_GUIDE, key):
            errors.append(f"docs/guides/self-host-env.md does not mention {key}")

    for key in ("SMEME_CORE_IMAGE", "POSTGRES_PASSWORD", "SMEME_PUBLIC_HOST"):
        if not _mentioned(ENV_GUIDE, key):
            errors.append(f"docs/guides/self-host-env.md does not mention {key}")
        if key != "SMEME_PUBLIC_HOST" and not _mentioned(ENV_EXAMPLE, key):
            errors.append(f".env.core.example does not mention {key}")

    guide = ENV_GUIDE.read_text(encoding="utf-8")
    for profile in REQUIRED_PROFILES:
        if f"<!-- {profile} -->" not in guide and f"#{profile}" not in guide.lower():
            # Accept explicit anchor ids
            if f'id="{profile}"' not in guide and f"## {profile}" not in guide:
                if f"### {profile.replace('profile-', '').replace('-', ' ')}" not in guide.lower():
                    pass
        marker = profile
        if marker not in guide:
            errors.append(f"docs/guides/self-host-env.md missing profile marker: {profile}")

    # Pull-only: no silent build on base compose
    if re.search(r"(?m)^\s+build:", compose_text):
        errors.append("docker-compose.core.yml must be pull-only (no build:)")

    if errors:
        print("Core operator env drift detected:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"OK: {len(operator_keys)} operator keys aligned "
        f"(compose ↔ .env.core.example ↔ self-host-env.md ↔ Settings)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
