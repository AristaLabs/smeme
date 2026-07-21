#!/usr/bin/env python3
"""Fail if Core code or image includes SaaS-only or development-only boundaries.

Modes:
  (default)  AST-scan KEEP packages for forbidden imports
  --image X  Also verify the appliance: forbidden files and packages are absent

Usage::

    uv run python scripts/check_core_no_saas_imports.py
    uv run python scripts/check_core_no_saas_imports.py --image smeme:local
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PREFIXES = (
    "smeme.landing",
    "smeme.legal",
    "smeme.saas_overlay",
    "smeme.billing.routes",
    "smeme.billing.stripe_sync",
    "smeme.billing.subscription_cancel",
    "smeme.billing.downgrade",
    "sendgrid",
    "stripe",
)

FORBIDDEN_MIDDLEWARE_NAMES = frozenset({"WorkflowPickRequiredMiddleware"})

# Paths that may import SAAS-ONLY modules (private overlay / Stripe adapters).
SAAS_ALLOWLIST_PREFIXES = (
    "smeme/saas_overlay.py",
    "smeme/landing/",
    "smeme/legal/",
    "smeme/billing/routes.py",
    "smeme/billing/stripe_sync.py",
    "smeme/billing/subscription_cancel.py",
    "smeme/billing/downgrade.py",
    "smeme/main.py",
)

FORBIDDEN_IMAGE_PATHS = (
    "smeme/main.py",
    "smeme/saas_overlay.py",
    "smeme/core/email.py",
    "smeme/landing",
    "smeme/legal",
    "smeme/billing/routes.py",
    "smeme/billing/stripe_sync.py",
    "smeme/billing/subscription_cancel.py",
    "smeme/billing/downgrade.py",
    "smeme/templates/billing",
    "smeme/templates/landing",
    "smeme/templates/legal",
    "smeme/templates/layouts/_analytics.html",
)

FORBIDDEN_IMAGE_PACKAGES = (
    "pytest",
    "pytest_alembic",
    "pytest_asyncio",
    "sendgrid",
    "stripe",
)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_saas_allowlisted(rel: str) -> bool:
    return any(rel == p or rel.startswith(p) for p in SAAS_ALLOWLIST_PREFIXES)


def _module_from_import(node: ast.AST) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            found.append((alias.name, None))
    elif isinstance(node, ast.ImportFrom):
        if node.module is None:
            return found
        for alias in node.names:
            found.append((node.module, alias.name))
    return found


def _scan_file(path: Path) -> list[str]:
    rel = _rel(path)
    if _is_saas_allowlisted(rel):
        return []
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: syntax error: {exc}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in FORBIDDEN_MIDDLEWARE_NAMES:
            violations.append(f"{rel}: defines SAAS-ONLY class {node.name}")
        for module, name in _module_from_import(node):
            for prefix in FORBIDDEN_PREFIXES:
                if module == prefix or module.startswith(prefix + "."):
                    violations.append(f"{rel}: imports {module}" + (f".{name}" if name else ""))
            if (
                module == "smeme.core.middleware"
                and name in FORBIDDEN_MIDDLEWARE_NAMES
                and not rel.endswith("saas_overlay.py")
            ):
                violations.append(f"{rel}: imports {module}.{name}")
    return violations


def scan_core_tree() -> list[str]:
    violations: list[str] = []
    smeme = ROOT / "smeme"
    for path in sorted(smeme.rglob("*.py")):
        violations.extend(_scan_file(path))
    factory = ROOT / "smeme" / "app_factory.py"
    if not factory.is_file():
        violations.append("missing smeme/app_factory.py")
    return violations


def _forbidden_runtime_path(archive_path: str) -> str | None:
    normalized = archive_path.removeprefix("./").lstrip("/")
    for rel in FORBIDDEN_IMAGE_PATHS:
        target = f"app/{rel}".rstrip("/")
        if normalized == target or normalized.startswith(target + "/"):
            return rel
    return None


def _check_image_layers(image: str) -> list[str]:
    """Inspect every final-image layer, including paths hidden by whiteouts."""
    violations: list[str] = []
    with tempfile.TemporaryDirectory(prefix="smeme-core-layers-") as tmp:
        archive = Path(tmp) / "image.tar"
        proc = subprocess.run(
            ["docker", "image", "save", "--output", str(archive), image],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "unknown docker error"
            return [f"image {image}: unable to export layers: {detail}"]

        try:
            with tarfile.open(archive) as image_tar:
                manifest_stream = image_tar.extractfile("manifest.json")
                if manifest_stream is None:
                    return [f"image {image}: docker archive has no manifest.json"]
                manifest = json.load(manifest_stream)
                layers = {
                    layer
                    for image_manifest in manifest
                    for layer in image_manifest.get("Layers", [])
                }
                for layer_name in sorted(layers):
                    layer_stream = image_tar.extractfile(layer_name)
                    if layer_stream is None:
                        violations.append(
                            f"image {image}: docker archive is missing layer {layer_name}"
                        )
                        continue
                    with tarfile.open(fileobj=layer_stream, mode="r|*") as layer_tar:
                        for member in layer_tar:
                            forbidden = _forbidden_runtime_path(member.name)
                            if forbidden is not None:
                                violations.append(
                                    f"image {image}: forbidden path {forbidden} "
                                    f"exists in layer {layer_name}"
                                )
        except (json.JSONDecodeError, OSError, tarfile.TarError, TypeError) as exc:
            violations.append(f"image {image}: unable to inspect layers: {exc}")
    return violations


def check_image(image: str) -> list[str]:
    violations = _check_image_layers(image)
    for rel in FORBIDDEN_IMAGE_PATHS:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                image,
                "-c",
                f"test ! -e /app/{rel}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            violations.append(f"image {image}: forbidden path present: {rel}")

    for package in FORBIDDEN_IMAGE_PACKAGES:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                image,
                "-c",
                (
                    "import importlib.util, sys; "
                    f"sys.exit(0 if importlib.util.find_spec({package!r}) is None else 1)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            violations.append(
                f"image {image}: Python package {package!r} is installed (must be absent)"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        help="Optional Core image tag to verify (all layers, final files, and packages)",
    )
    args = parser.parse_args(argv)

    violations = scan_core_tree()
    if args.image:
        violations.extend(check_image(args.image))

    if violations:
        print("❌ Core boundary violations (D022/D023):")
        for v in sorted(set(violations)):
            print(f"  - {v}")
        return 1

    print("✅ Core tree has no SAAS-ONLY imports outside allowlisted overlay paths")
    if args.image:
        print(f"✅ Image {args.image}: forbidden paths absent from every layer and packages absent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
