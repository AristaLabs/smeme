# D026 Clerk SDK spike notes

**Date:** 2026-07-26  
**SDK:** `clerk-backend-api==5.0.6` (Core `.venv`)  
**Purpose:** Lock Python attribute paths before coding D026 gates.

## Confirmed fields

| Concept | Python path | Type / notes |
|---------|-------------|--------------|
| Primary email id | `User.primary_email_address_id` | `Nullable[str]` |
| Email list | `User.email_addresses` | `List[EmailAddress]` |
| Email string | `EmailAddress.email_address` | `str` |
| Verification | `EmailAddress.verification` | Discriminated union (OTP/Admin/OAuth/Ticket/SAML/EmailLink); may be null |
| Verification status | `EmailAddress.verification.status` | Enum / string; gate on exact **`verified`** (`VerificationStatus.VERIFIED`) |
| Legal acceptance | `User.legal_accepted_at` | `Nullable[int]` — **Unix seconds**; `null` if express consent disabled or not accepted |

## Gate helpers (to implement)

1. Resolve primary `EmailAddress` by `primary_email_address_id`; if missing, first address (legacy fallback only for email string — **verification still required** on the resolved primary when id is set).
2. If no primary email → `primary_email_missing`.
3. If `verification` is null or `status != "verified"` → `email_not_verified`.
4. If `legal_accepted_at` is null → `legal_consent_required`.
5. Convert `legal_accepted_at` int → `datetime.fromtimestamp(ts, tz=UTC)`.

## Re-consent semantics (docs + ops)

- Clerk sets `legal_accepted_at` when express consent is enabled and the user accepts.
- Changing Clerk Legal Compliance document URLs / requiring re-acceptance is an **operator/Clerk** action; SMEme records **config version constants** (`TERMS_VERSION` / `PRIVACY_VERSION`) at provision time, not HTML scrapes.
- SMEme does **not** clear local audit on Clerk re-consent for grandfathered users; new provisions always require non-null Clerk `legal_accepted_at` at create/link time.
- Runbook sequence: update hosted legal pages → update Clerk Legal links → bump SaaS version constants → rely on Clerk to prompt re-acceptance when configured.

## JWT note

OAuth access tokens used by MCP do **not** carry email verification or `legal_accepted_at`. Always use Clerk Backend API `users.get_async(user_id=sub)` for first-provision gates.

## Staging manual matrix (operator)

Run on staging with Clerk Legal Compliance + email verification enabled, Terms/Privacy URLs pointing at staging `/legal/*`, and SaaS version constants set. Keep `MCP_FIRST_PROVISIONING_ENABLED=false` until migration is live.

| Case | Expect |
|------|--------|
| Flag off + unlinked OAuth | `auth_reason=no_local_user_for_clerk_sub`; no `users` row |
| Flag on + verified + `legal_accepted_at` set | First tool call creates one Free user; audit columns filled from Clerk timestamp + config versions |
| Email signup missing verify | `email_not_verified`; no row |
| Consent not accepted | `legal_consent_required`; no row |
| Social signup same gates | Same as email path |
| Existing linked user (null audit) | Tools succeed (grandfather); no forced re-consent |
| Incomplete `SMEME_LEGAL_*` + flag on | `legal_config_incomplete` on first-provision only |
| After success | `list` / `guidance_get` work without a prior web visit |

Then enable the flag in staging, monitor provision telemetry (`created`, `blocked`, `rate_limited`, `race_reused`), then prod.
