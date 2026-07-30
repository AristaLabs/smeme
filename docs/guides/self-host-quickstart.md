# Self-host quickstart (SMEme Core)

Pull the **public** Core image, start Postgres, and reach health on loopback.
Auth, MCP, and the AI wizard are **not** required for health — see
[self-host-pilot.md](self-host-pilot.md) after this page.

**Healthy ≠ usable product.** `/api/v1/health` only means the process and DB
probe succeeded. Browser login, Deploy, Listed trees, and MCP OAuth need Clerk
(and usually HTTPS).

## Requirements

- Docker + Docker Compose **v2.24+** (prod overlay uses `!reset`)
- Outbound pull access to `ghcr.io` (package is public; no login required)
- Optional later: Clerk, OpenAI/Tavily — [env reference](self-host-env.md)

## Zero to health (operator pull path)

```bash
git clone https://github.com/AristaLabs/smeme.git
cd smeme
git checkout v0.9.9   # or newer operator-bundle tag when published

./scripts/init_core_env.sh
# Creates .env.core (mode 600). Refuses to overwrite an existing file.

docker compose --env-file .env.core -f docker-compose.core.yml pull
docker compose --env-file .env.core -f docker-compose.core.yml up -d --no-build --wait

curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/health/db
```

- App (loopback): http://127.0.0.1:8000 → redirects toward `/decision-trees/dashboard`
- Default image in `.env.core.example`: `ghcr.io/aristalabs/smeme:v0.9.9`
- Prefer digest pins in production — see [self-host-env.md](self-host-env.md)

**Network (H-07):** Postgres is **not** published on the host. Web binds
**`127.0.0.1:8000` only**. Product routes need auth; `/api/docs` and health stay
on loopback. Internet-facing: use the [production overlay](#production-overlay-https--caddy).

Empty `SECRET_KEY` / `JWT_SECRET_KEY` / `POSTGRES_PASSWORD` fail closed (Compose
refuses to interpolate).

### Next steps after health

| Goal | Doc |
|------|-----|
| Env knobs / profiles | [self-host-env.md](self-host-env.md) |
| HTTPS | [below](#production-overlay-https--caddy) |
| Clerk + MCP + wizard | [self-host-pilot.md](self-host-pilot.md) |
| Backup / upgrade | [Operate](#operate-backup-upgrade-troubleshoot) |

## Production overlay (HTTPS / Caddy)

```bash
# In .env.core — matching examples:
BASE_URL=https://app.example.com
ALLOWED_ORIGINS=["https://app.example.com"]
SMEME_PUBLIC_HOST=app.example.com

mkdir -p deploy/caddy/certs
# Lab only (self-signed):
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout deploy/caddy/certs/tls.key \
  -out deploy/caddy/certs/tls.crt \
  -subj "/CN=app.example.com"
# Prefer publicly trusted certs for real pilots (replace tls.crt / tls.key).

docker compose --env-file .env.core \
  -f docker-compose.core.yml -f docker-compose.core.prod.yml pull
docker compose --env-file .env.core \
  -f docker-compose.core.yml -f docker-compose.core.prod.yml \
  up -d --no-build --wait
```

- `SMEME_PUBLIC_HOST` is passed into the Caddy container (see
  [`deploy/caddy/Caddyfile`](../../deploy/caddy/Caddyfile)).
- Loopback `:8000` publish is removed; ingress is **80/443** only.
- `web` / `db` / `caddy` use `restart: unless-stopped`.

## Contributor build (separate from operator path)

Operators should **not** need this. Contributors building local code:

```bash
./scripts/init_core_env.sh
docker compose --env-file .env.core \
  -f docker-compose.core.yml -f docker-compose.core.build.yml \
  up -d --build --wait
```

Or: `docker build -f Dockerfile.core -t smeme-core:local .`

Release evidence pack: `scripts/prepare_core_release_evidence.sh smeme-core:local build/release-evidence`.

## Operate, backup, upgrade, troubleshoot

### Status / logs / stop

```bash
docker compose --env-file .env.core -f docker-compose.core.yml ps
docker compose --env-file .env.core -f docker-compose.core.yml logs -f web
docker compose --env-file .env.core -f docker-compose.core.yml stop
# Tear down containers + network; keep volumes:
docker compose --env-file .env.core -f docker-compose.core.yml down
```

### Danger: `down -v`

`docker compose … down -v` **deletes** the Postgres volume (`smeme_core_pg`) and
Caddy data volumes. That destroys decision-trees and auth-linked rows. Prefer
`down` without `-v` unless you intend a wipe.

### Backup / restore test

```bash
# Dump (while stack is up)
docker compose --env-file .env.core -f docker-compose.core.yml exec -T db \
  pg_dump -U smeme -d smeme -Fc > smeme-core-$(date +%Y%m%d).dump

# Restore into a fresh volume (smoke the backup before you need it)
docker compose --env-file .env.core -f docker-compose.core.yml exec -T db \
  pg_restore -U smeme -d smeme --clean --if-exists < smeme-core-YYYYMMDD.dump
```

After restore, hit `/api/v1/health/db` and spot-check the dashboard.

### Upgrade / rollback

1. Note current `SMEME_CORE_IMAGE` (tag **and** digest if pinned).
2. `pg_dump` as above.
3. Set `SMEME_CORE_IMAGE` to the new tag/digest → `pull` → `up -d --no-build --wait`.
4. Migrations run on container start; watch `logs web` if health stalls.
5. **Rollback:** point `SMEME_CORE_IMAGE` at the previous digest and recreate
   `web`. If a migration is not backward-compatible, restore the dump taken in
   step 2 onto a volume that matches that image generation.

Pair upgrades with rollbacks: never drop the previous digest from your notes
until the new tag is proven.

### Secret rotation

1. Generate new values (`openssl rand -hex 32` / init script on a throwaway copy).
2. Update `.env.core`; recreate `web` for `SECRET_KEY` / `JWT_SECRET_KEY`.
3. `POSTGRES_PASSWORD` changes require aligning the DB role (`ALTER USER`) or
   recreating the volume from backup — do not only change the env file.

### Troubleshooting

| Symptom | Check |
|---------|--------|
| Compose: “required variable … missing a value” | Run `init_core_env.sh` or fill secrets; empty strings fail closed. |
| `pull` 401 / denied | Package must be public; `docker logout ghcr.io` and retry with empty `DOCKER_CONFIG` if Desktop creds interfere. |
| Health fails / start_period | `docker compose … logs web`; confirm DB healthy; wait for migrations. |
| Caddy serves wrong host / TLS errors | `SMEME_PUBLIC_HOST` set; certs under `deploy/caddy/certs/`; `BASE_URL` is `https://` matching that host. |
| MCP client cannot discover OAuth | HTTPS `BASE_URL`; `MCP_ENABLED=true`; see [self-host-pilot.md](self-host-pilot.md). |
| Wizard 500 / boot refuses OpenAI | `SMEME_AI_GENERATION_ENABLED=true` requires `OPENAI_API_KEY`. |

## Sovereignty (short)

Deploy / evaluate / MCP report stay on your host by default. Wizard + Tavily
send content off-box. Full matrix: [self-host-env.md](self-host-env.md) and the
sovereignty section historically in this guide’s older revisions — prefer the
env guide + [authoring-decision-trees.md](authoring-decision-trees.md).

## Stuck?

[GitHub Discussions → Self-host / operators](https://github.com/AristaLabs/smeme/discussions/categories/self-host-operators).
Include image tag/digest; never paste a full `.env`.

## Contributor checks

```bash
uv run python scripts/check_core_no_saas_imports.py
uv run python scripts/check_core_operator_env_drift.py
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md).
