# Auth Routes

> **Auth is handled by Clerk.** The platform does not have its own register/login/password-reset endpoints. Sign-in, sign-up, email verification, and password reset all go through Clerk's hosted UI. The routes below are the SMEme-side handlers that Clerk redirects to.

## Sign-in / Sign-up

### GET /auth/login

Redirects to Clerk's hosted sign-in page. If the user is already signed in, redirects to `/qnr/dashboard`.

### GET /auth/register

Redirects to Clerk's hosted sign-up page. If the user is already signed in, redirects to `/qnr/dashboard`.

### GET /auth/clerk-callback

Clerk calls this after a successful sign-in or sign-up. Creates or updates the local `User` row from the Clerk session, sets the SMEme session cookie, and redirects to the dashboard.

### GET /auth/logout

Clears the SMEme session cookie and redirects to the landing page.

---

## Profile

These routes require an active session (cookie auth).

### GET /auth/profile/me

Returns the current user's profile data.

**Auth:** Required

**Response:** JSON `UserRead` object

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "username",
  "is_active": true,
  "is_verified": true,
  "clerk_user_id": "user_...",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### PUT /auth/profile/me

Update username, display name, or bio.

**Auth:** Required

**Body:** JSON with fields to update (username, etc.)

### GET /auth/profile/dashboard

Returns the authenticated user's profile dashboard page (HTML).

**Auth:** Required

---

## Webhook

### POST /auth/clerk/webhook

Receives Clerk webhook events (user created, updated, deleted) to keep the local `User` table in sync with Clerk.

Requires `CLERK_WEBHOOK_SECRET` to be configured. Returns HTTP 500 if the secret is not set.

---

**See also:** [QNR Routes](qnr-routes.md) | [Memo Routes](memo-routes.md)
