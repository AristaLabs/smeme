# Authentication & Profile Management

> **Clerk-era identity (2026-06):** **Clerk** owns sign-in via **email verification codes** (default); optional password and name in Account Portal (2FA optional when enabled in Clerk). The app handle in UI is **email**. **`users.username`** is an SMEme-internal unique slug from the email local-part at first sync—not a Clerk username. Editable **creator aliases** are planned for **Business** tier (Coming Soon); `/creator/{slug}` is provisional when marketplace UI is on. Sections below that describe FastAPI-Users registration, password reset, and editable username/email are **legacy** (pre-Clerk HTML routes removed).

## Overview

The SMEme Platform provides comprehensive user authentication and profile management with:

- Cookie-based sessions (FastAPI-Users)
- Profile dashboard with activity statistics
- Secure password management
- Email verification system
- HTMX-powered modal interfaces

## Authentication Flow

### Registration
1. User submits registration form via HTMX
2. FastAPI-Users creates account with Argon2id password hashing
3. User is redirected to login with success message
4. Email verification token generated (configurable)

### Login
1. Cookie-based authentication with HTTP-only, samesite=lax cookies
2. Automatic session management and CSRF protection
3. Redirect to dashboard on success

### Session Management
- Cookies expire based on `ACCESS_TOKEN_EXPIRE_MINUTES` setting
- Automatic logout on session timeout
- Secure logout clears all session data

## Profile Management

### Dashboard Features

**User Statistics:**
- QNRs Created: Count of questionnaires authored by user
- Sessions Completed: Number of completed questionnaire sessions
- Memos Generated: AI-generated memos from sessions
- Public QNRs: Count of published questionnaires

**Activity Feed:**
- Recent user actions (session starts, completions)
- Chronological ordering (most recent first)
- Limited to recent activity for performance

### Profile Editing

**Modal-Based Interface:**
- HTMX-powered modal dialogs
- Client-side form validation
- Server-side validation with detailed error messages

**Available Actions:**
- Edit username and email
- Change password (with current password validation)
- Request email verification

## Security Implementation

### Password Management

**Hashing:**
- Argon2id algorithm (FastAPI-Users default)
- Configurable rounds for security/performance balance

**Password Change Process:**
1. User provides current password, new password, confirmation
2. Current password validated against stored hash
3. New password hashed and stored
4. Session remains active (no forced logout)

### Email Verification

**Token Generation:**
- Cryptographically secure tokens
- Time-limited validity
- Single-use tokens (consumed on verification)

**Email Delivery:**
- Configurable SMTP/SendGrid/SES backends
- HTML and plain text templates
- Error handling for delivery failures

## Technical Implementation

### FastAPI-Users Integration

**Backend Configuration:**
```python
# Cookie-based authentication
auth_backend_cookie = CookieTransport(
    cookie_name="session",
    cookie_max_age=1800,  # 30 minutes
    cookie_secure=False,  # HTTPS in production
    cookie_httponly=True,
    cookie_samesite="lax",
)

# User manager with custom logic
class UserManager(BaseUserManager[User, UUID]):
    # Custom hooks for registration, login, verification
```

**Dependency Injection:**
```python
# Centralized dependencies (FastAPI 2025 pattern)
CurrentUser = Annotated[User, Depends(current_active_user)]
AsyncSessionDep = Annotated[AsyncSession, Depends(get_db)]
UserManagerDep = Annotated[UserManager, Depends(get_user_manager)]
```

### Database Models

**User Model Extensions:**
- Standard FastAPI-Users fields (email, hashed_password, etc.)
- Additional fields: username, timestamps
- Relationship to QNRs, sessions, memos

**Session Tracking:**
- Cookie-based session management
- No server-side session storage (stateless)
- Automatic cleanup on logout

### HTMX Integration

**Modal Management:**
```html
<!-- Modal container in base template -->
<div id="modal-container"></div>

<!-- Trigger modal loading -->
<button hx-get="/auth/profile/edit-modal"
        hx-target="#modal-container"
        hx-swap="innerHTML"
        hx-on::after-request="if(event.detail.successful) showModal()">
  Edit Profile
</button>
```

**Form Handling:**
- Progressive enhancement (works without JavaScript)
- Server-side validation with client feedback
- Real-time field validation

## Configuration

### Required Settings

```bash
# Database
DATABASE_URL=postgresql+asyncpg://...

# Security
SECRET_KEY=your-secret-key-minimum-32-characters
JWT_SECRET_KEY=your-jwt-secret-minimum-32-characters

# Email (optional for local development)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=noreply@yourdomain.com
```

### Environment-Specific Setup

**Development:**
- Email verification logged to console (no SMTP required)
- Debug logging enabled
- Cookie security relaxed

**Production:**
- HTTPS required for secure cookies
- Email delivery configured
- Enhanced logging and monitoring

## API Endpoints

### Authentication Routes

**POST /auth/register**
- User registration with validation
- Returns user object or validation errors

**POST /auth/cookie/login**
- Cookie-based authentication
- Form-encoded: `username=email&password=pass`
- Sets HTTP-only session cookie

**POST /auth/logout**
- Clears session cookie
- Redirects to login page

### Profile Routes

**GET /auth/profile/dashboard**
- User dashboard with statistics and activity
- Requires authentication

**PATCH /auth/profile/me**
- Update user profile (username, email)
- Requires authentication

**POST /auth/profile/change-password**
- Secure password change with current validation
- Requires authentication

**POST /auth/profile/request-verify-token**
- Trigger email verification
- Requires authentication

**POST /auth/verify**
- Verify email with token
- Public endpoint (no auth required)

## Error Handling

### Authentication Errors

**Invalid Credentials:**
- HTTP 400 with generic message
- No information leakage about user existence

**Session Expired:**
- HTTP 401 or redirect to login
- Automatic redirect handling

### Validation Errors

**Password Requirements:**
- Minimum length, complexity rules
- Client and server validation

**Email Format:**
- RFC-compliant email validation
- Duplicate email prevention

## Performance Considerations

### Session Management
- Stateless cookie-based sessions (no DB queries)
- Lightweight session validation
- Automatic cleanup on logout

### Profile Statistics
- Efficient database queries with proper indexing
- Cached statistics where appropriate
- Limited activity feed (recent items only)

### Email Operations
- Asynchronous email sending
- Queue-based processing for high volume
- Retry logic for delivery failures

## Security Best Practices

### Password Security
- Argon2id hashing with appropriate parameters
- No plaintext password storage
- Secure password change flow

### Session Security
- HTTP-only cookies prevent XSS attacks
- SameSite protection against CSRF
- Secure cookies in production (HTTPS only)

### API Security
- Input validation on all endpoints
- Rate limiting for authentication attempts
- Audit logging for security events

## Testing Strategy

### Authentication Tests
- User registration and login flows
- Password validation and change
- Session management and logout
- Email verification process

### Profile Tests
- Dashboard data accuracy
- Profile update functionality
- Modal interactions
- Error handling and validation

### Security Tests
- SQL injection prevention
- XSS protection
- CSRF protection
- Session fixation attacks

## Monitoring & Observability

### Key Metrics
- Authentication success/failure rates
- Password change frequency
- Email verification completion rates
- Session duration statistics

### Logging
- Authentication events (login, logout, registration)
- Password changes with user context
- Email verification attempts
- Security-related incidents

---

**Next:** [Database Architecture](database.md){ .md-button }

**🔄 Auto-reload test - Tue Dec 30 09:29:04 EST 2025**
**🔄 Dirty reload test - Tue Dec 30 09:32:00 EST 2025**
